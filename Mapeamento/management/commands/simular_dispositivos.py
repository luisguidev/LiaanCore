"""Simula N dispositivos observando o tempo real do painel.

Cada "dispositivo" é uma sessão HTTP independente, com cookie jar próprio,
exatamente como navegadores diferentes. O comando percorre o caminho que o
`realtime.js` faz no navegador:

  1. login independente por dispositivo
  2. GET /agendamento/estado/ guardando o ETag
  3. reenvio do mesmo ETag -> 304 quando nada mudou
  4. um dispositivo agenda -> os OUTROS devem receber 200 e enxergar a reserva
  5. pode_excluir difere entre o dono e os demais
  6. o dono cancela -> a reserva some de todos

Os testes automatizados provam o contrato do servidor; isto prova que um
cliente HTTP real consegue consumir esse contrato.

Uso (servidor em outro terminal):

    python manage.py runserver
    python manage.py simular_dispositivos

ATENÇÃO: escreve no banco de desenvolvimento. Cria/reusa os usuários
`disp1..N` (eles ficam, para você entrar e olhar) e remove os agendamentos
criados ao final. Use --manter para deixar o agendamento no banco.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from http.cookiejar import CookieJar
from urllib.error import HTTPError

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from Mapeamento.models import Agendamento, Computador

SENHA_PADRAO = 'senha-dispositivo-123'
TIMEOUT = 10
FORMATO = '%Y-%m-%dT%H:%M'
CSRF_RE = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')


class Dispositivo:
    """Um navegador: sessão, cookies e ETag próprios."""

    def __init__(self, nome, url_base, usuario, senha):
        self.nome = nome
        self.url_base = url_base.rstrip('/')
        self.usuario = usuario
        self.senha = senha
        self.etag = None
        self.dados = None
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def _abrir(self, requisicao):
        return self.opener.open(requisicao, timeout=TIMEOUT)

    def _csrf(self, caminho):
        corpo = self._abrir(f'{self.url_base}{caminho}').read().decode()
        achado = CSRF_RE.search(corpo)
        if not achado:
            raise RuntimeError(
                f'{self.nome}: token CSRF não encontrado em {caminho}'
            )
        return achado.group(1)

    def _postar(self, caminho, dados, cabecalhos=None):
        corpo = urllib.parse.urlencode(dados).encode()
        requisicao = urllib.request.Request(
            f'{self.url_base}{caminho}', data=corpo, headers=cabecalhos or {}
        )
        return self._abrir(requisicao)

    def entrar(self):
        login = '/accounts/login/'
        resposta = self._postar(login, {
            'csrfmiddlewaretoken': self._csrf(login),
            'username': self.usuario,
            'password': self.senha,
        })
        # Login malsucedido deixa a view renderizar o form de novo.
        if '/accounts/login/' in resposta.geturl():
            raise RuntimeError(
                f'{self.nome}: login falhou para {self.usuario} '
                f'(HTTP {resposta.status})'
            )

    def estado(self):
        """GET /agendamento/estado/ reenviando o If-None-Match conhecido.

        Devolve (status, etag, dados). Num 304 não há corpo no servidor, então
        `dados` é o último snapshot recebido — que é exatamente o que o
        navegador teria em mãos (ele não re-renderiza nada num 304).
        """
        cabecalhos = {'If-None-Match': self.etag} if self.etag else {}
        try:
            resposta = self._abrir(urllib.request.Request(
                f'{self.url_base}/agendamento/estado/', headers=cabecalhos
            ))
        except HTTPError as e:
            # urllib trata 304 como erro; é a resposta esperada aqui.
            if e.code != 304:
                raise
            return 304, self.etag, self.dados

        self.etag = resposta.headers.get('ETag')
        self.dados = json.loads(resposta.read().decode())
        return resposta.status, self.etag, self.dados

    def agendar(self, computador_id, inicio, fim):
        return self._postar('/agendamento/agendar/', {
            'csrfmiddlewaretoken': self._csrf('/agendamento/'),
            'computador': str(computador_id),
            'horario_inicio': inicio.strftime(FORMATO),
            'horario_fim': fim.strftime(FORMATO),
        })

    def excluir(self, agendamento_id):
        resposta = self._postar(
            f'/agendamento/{agendamento_id}/excluir/',
            {'csrfmiddlewaretoken': self._csrf('/agendamento/')},
            cabecalhos={'X-Requested-With': 'XMLHttpRequest'},
        )
        return json.loads(resposta.read().decode())


class Command(BaseCommand):
    help = 'Simula vários dispositivos logados no painel ao mesmo tempo.'

    def add_arguments(self, parser):
        parser.add_argument('--url', default='http://127.0.0.1:8000',
                            help='Endereço do servidor '
                                 '(padrão: http://127.0.0.1:8000)')
        parser.add_argument('--dispositivos', type=int, default=3,
                            help='Quantos dispositivos participam (padrão: 3)')
        parser.add_argument('--senha', default=SENHA_PADRAO,
                            help='Senha dos usuários de teste')
        parser.add_argument('--intervalo', type=float, default=5.0,
                            help='Segundos entre um poll e o outro (padrão: 5.0, '
                                 'o mesmo do realtime.js)')
        parser.add_argument('--espera', type=float, default=12.0,
                            help='Tempo máximo para a reserva chegar aos outros '
                                 '(padrão: 12s, ~2 ciclos de poll)')
        parser.add_argument('--manter', action='store_true',
                            help='Não cancela o agendamento no final')

    def handle(self, *args, **opcoes):
        total = opcoes['dispositivos']
        if total < 2:
            self.stderr.write(
                'Use pelo menos 2 dispositivos: um agenda e os outros observam.'
            )
            return

        pc = Computador.objects.first()
        if pc is None:
            self.stderr.write(
                'Nenhum computador no banco. Carregue a fixture primeiro:\n'
                '  python manage.py loaddata agencia'
            )
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\nSimulando {total} dispositivos em {opcoes["url"]}'
        ))
        self.stdout.write(f'Computador em disputa: {pc.nome} (id={pc.pk})')

        dispositivos = self._preparar_dispositivos(
            total, opcoes['senha'], opcoes['url']
        )

        try:
            falhas = self._rodar(dispositivos, pc, opcoes)
        except (urllib.error.URLError, RuntimeError) as erro:
            self.stderr.write(self.style.ERROR(f'\nERRO: {erro}'))
            self.stderr.write(
                f'\nO servidor responde em {opcoes["url"]}? Rode em outro terminal:\n'
                f'  python manage.py runserver'
            )
            return
        finally:
            removidos = Agendamento.objects.filter(
                usuario__username__in=[d.usuario for d in dispositivos]
            ).delete()[0]
            if removidos:
                self.stdout.write(f'Limpeza: {removidos} agendamento(s) de teste '
                                  f'removido(s).')

        if falhas:
            self.stdout.write(self.style.ERROR(
                f'\n{len(falhas)} verificação(ões) FALHARAM:'
            ))
            for falha in falhas:
                self.stdout.write(f'  - {falha}')
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS(
            '\nTudo certo: os dispositivos enxergam as alterações uns dos outros.\n'
        ))

    def _preparar_dispositivos(self, total, senha, url_base):
        dispositivos = []
        for i in range(1, total + 1):
            nome = f'disp{i}'
            usuario, _ = User.objects.get_or_create(username=nome)
            usuario.set_password(senha)
            usuario.is_active = True
            usuario.save()
            dispositivos.append(
                Dispositivo(f'[disp{i}]', url_base, nome, senha)
            )
        return dispositivos

    # ------------------------------------------------------------------
    def _rodar(self, dispositivos, pc, opcoes):
        falhas = []

        self.stdout.write('\n1) login independente em cada dispositivo')
        for d in dispositivos:
            d.entrar()
            self.stdout.write(f'   {d.nome} autenticado como {d.usuario}')

        self.stdout.write('\n2) primeira leitura de /agendamento/estado/')
        for d in dispositivos:
            status, etag, _ = d.estado()
            self.stdout.write(f'   {d.nome} HTTP {status}  ETag {etag}')

        self.stdout.write('\n3) reenviando o mesmo ETag (nada mudou)')
        for d in dispositivos:
            status, _, _ = d.estado()
            ok = status == 304
            if not ok:
                falhas.append(f'{d.nome} devolveu {status} em vez de 304')
            self.stdout.write(f'   {d.nome} HTTP {status} {self._marca(ok)}')

        self.stdout.write(
            f'\n4) {dispositivos[0].nome} agenda; os demais devem ver em '
            f'<={opcoes["espera"]:.0f}s'
        )
        autor = dispositivos[0]
        autor_user = User.objects.get(username=autor.usuario)
        inicio = timezone.localtime(timezone.now() + timedelta(hours=30))
        fim = inicio + timedelta(hours=2)

        agendamento = None
        try:
            autor.agendar(pc.pk, inicio, fim)
            agendamento = (
                Agendamento.objects.filter(usuario=autor_user, cancelado=False)
                .order_by('-id')
                .first()
            )
        except (RuntimeError, urllib.error.URLError, HTTPError) as erro:
            self.stdout.write(f'   {self.style.ERROR("agendar falhou")}: {erro}')

        if agendamento is None:
            # Sucesso e erro de formulário dão HTTP 200 na view; só o banco
            # distingue os dois casos.
            falhas.append('o agendamento do dispositivo 1 não foi criado')
            self.stdout.write(f'   {self.style.ERROR("FALHOU")}: nenhum agendamento '
                              f'foi gravado (conflito ou horário inválido?)')
            return falhas

        self.stdout.write(f'   {autor.nome} criou o agendamento id={agendamento.id} '
                          f'em {pc.nome}: {inicio:%d/%m %H:%M} - {fim:%H:%M}')

        for d in dispositivos[1:]:
            self._esperar_reserva(d, agendamento.id, opcoes, falhas)

        self.stdout.write('\n5) pode_excluir por dispositivo (ETag é por usuário)')
        for d in dispositivos:
            status, etag, dados = d.estado()
            visto = next(
                (a for c in dados['computadores']
                 for a in c['agendamentos'] if a['id'] == agendamento.id),
                None,
            )
            esperado = d.usuario == autor.usuario
            if visto is None:
                falhas.append(f'{d.nome} não enxerga a reserva criada')
                marca = self.style.ERROR('NÃO VIU')
            elif visto['pode_excluir'] != esperado:
                falhas.append(
                    f'{d.nome} recebeu pode_excluir={visto["pode_excluir"]}, '
                    f'esperado {esperado}'
                )
                marca = self.style.ERROR('PERMISSÃO ERRADA')
            else:
                marca = self.style.SUCCESS(f'pode_excluir={visto["pode_excluir"]} OK')
            self.stdout.write(f'   {d.nome} ETag {etag}  {marca}')

        if opcoes['manter']:
            return falhas

        self.stdout.write('\n6) o dono cancela; a reserva deve sumir para todos')
        try:
            resposta = autor.excluir(agendamento.id)
            self.stdout.write(f'   {autor.nome}: "{resposta.get("mensagem")}"')
        except (RuntimeError, urllib.error.URLError, HTTPError) as erro:
            falhas.append(f'exclusão falhou: {erro}')
            self.stdout.write(f'   {self.style.ERROR("FALHOU")}: {erro}')
            return falhas

        for d in dispositivos:
            status, _, dados = d.estado()
            ainda = any(
                a['id'] == agendamento.id
                for c in dados['computadores'] for a in c['agendamentos']
            )
            ok = not ainda and status == 200
            if ainda:
                falhas.append(f'{d.nome} ainda enxerga a reserva cancelada')
            if status != 200:
                falhas.append(
                    f'{d.nome} recebeu {status} após o cancelamento; o navegador '
                    f'nunca receberia a reserva removida'
                )
            self.stdout.write(f'   {d.nome} HTTP {status} ainda visível={ainda} '
                              f'{self._marca(ok)}')

        return falhas

    def _esperar_reserva(self, dispositivo, alvo, opcoes, falhas):
        """Faz polling até a reserva aparecer ou o tempo acabar."""
        limite = time.monotonic() + opcoes['espera']
        polls = 0
        while time.monotonic() < limite:
            polls += 1
            status, _, dados = dispositivo.estado()
            achou = any(
                a['id'] == alvo
                for c in (dados or {}).get('computadores', [])
                for a in c['agendamentos']
            )
            if achou:
                ok = status != 304
                if not ok:
                    falhas.append(
                        f'{dispositivo.nome} recebeu 304 e mesmo assim veio '
                        f'dado novo — o browser não re-renderizaria'
                    )
                self.stdout.write(
                    f'   {dispositivo.nome} poll {polls}: HTTP {status} e VIU a '
                    f'reserva {self._marca(ok)}'
                )
                return
            time.sleep(opcoes['intervalo'])

        falhas.append(
            f'{dispositivo.nome} não viu a reserva em {opcoes["espera"]:.0f}s'
        )
        self.stdout.write(
            f'   {dispositivo.nome} {self.style.ERROR("NÃO VIU")} após '
            f'{polls} polls'
        )

    def _marca(self, ok):
        return self.style.SUCCESS('OK') if ok else self.style.ERROR('FALHOU')