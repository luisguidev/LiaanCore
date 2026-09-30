"""Testes do app Mapeamento.

Cobrem as regras de negócio que antes não tinham nenhum teste:
conflito de horário, soft delete, permissão de exclusão, cálculo de status,
filtro de horários livres e o contrato de ETag do polling.
"""

from datetime import timedelta
import threading

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .forms import AgendamentoForm
from .models import Agendamento, Computador
from .status import STATUS_DISPONIVEL, STATUS_MANUTENCAO, STATUS_OCUPADO, calcular_status
from .views import INTERVALO_MINUTOS


def daqui_horas(horas):
    """Instante no futuro, truncado ao minuto.

    O truncamento é necessário porque o formulário só envia minuto; sem ele
    um agendamento criado às 18:52:37 e outro às 18:52:00 seriam vistos como
    sobrepostos por 37 segundos.
    """
    return (timezone.now() + timedelta(hours=horas)).replace(second=0, microsecond=0)


def como_input(momento):
    """Formata no fuso LOCAL, que é o que o formulário espera receber.

    Sem esta conversão o teste misturaria UTC com America/Sao_Paulo e
    produziria falsos "sem conflito".
    """
    return timezone.localtime(momento).strftime('%Y-%m-%dT%H:%M')


def amanha_hora(hora):
    """Amanhã no horário local — usado para não depender do horário atual."""
    amanha = timezone.localtime().date() + timedelta(days=1)
    return timezone.make_aware(
        timezone.datetime.combine(amanha, timezone.datetime.min.time()) + timedelta(hours=hora),
        timezone.get_current_timezone(),
    )


class TesteBase(TestCase):
    def setUp(self):
        cache.clear()
        self.pc = Computador.objects.create(
            nome='liaan-01', placa_de_video='RTX 4090',
            ip_lm_studio='192.168.0.1', id_anydesk='111 222 333',
        )
        self.pc2 = Computador.objects.create(nome='liaan-02', placa_de_video='A6000')
        self.dono = User.objects.create_user('ana', password='senha-forte-123')
        self.outro = User.objects.create_user('bruno', password='senha-forte-123')
        self.admin = User.objects.create_user('root', password='senha-forte-123', is_staff=True)


# ---------------------------------------------------------------------------
# Criação de agendamento
# ---------------------------------------------------------------------------

class TesteCriacaoAgendamento(TesteBase):
    def dados(self, pc=None, inicio_horas=2, fim_horas=3, **extra):
        pc = pc or self.pc
        dados = {
            'computador': str(pc.pk),
            'horario_inicio': como_input(daqui_horas(inicio_horas)),
            'horario_fim': como_input(daqui_horas(fim_horas)),
        }
        dados.update(extra)
        return dados

    def test_cria_agendamento_valido(self):
        form = AgendamentoForm(self.dados())
        self.assertTrue(form.is_valid(), form.errors)

        agendamento = form.save(usuario=self.dono)

        self.assertEqual(agendamento.usuario, self.dono)
        self.assertEqual(agendamento.computador, self.pc)
        self.assertFalse(agendamento.cancelado)

    def test_rejeita_fim_antes_do_inicio(self):
        form = AgendamentoForm(self.dados(inicio_horas=5, fim_horas=4))
        self.assertFalse(form.is_valid())
        self.assertIn('anterior ao horário final', str(form.errors))

    def test_rejeita_horario_no_passado(self):
        form = AgendamentoForm(self.dados(inicio_horas=-5, fim_horas=-4))
        self.assertFalse(form.is_valid())
        self.assertIn('futuro', str(form.errors))

    def test_rejeita_computador_inexistente(self):
        form = AgendamentoForm(self.dados(computador='9999'))
        self.assertFalse(form.is_valid())
        self.assertIn('computador', str(form.errors).lower())

    def test_banco_recusa_fim_menor_que_inicio(self):
        """O CheckConstraint é a última linha de defesa."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Agendamento.objects.create(
                    computador=self.pc, usuario=self.dono,
                    horario_inicio=daqui_horas(3), horario_fim=daqui_horas(2),
                )


# ---------------------------------------------------------------------------
# Conflito de horário
# ---------------------------------------------------------------------------

class TesteConflito(TesteBase):
    def test_rejeita_sobreposicao_total(self):
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )
        form = AgendamentoForm({
            'computador': str(self.pc.pk),
            'horario_inicio': como_input(daqui_horas(3)),
            'horario_fim': como_input(daqui_horas(5)),
        })
        self.assertFalse(form.is_valid())
        self.assertIn('Conflito de horário', str(form.errors))

    def test_permite_horarios_adjacentes(self):
        """Um bloco terminando exatamente quando o outro começa não é conflito."""
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )
        form = AgendamentoForm({
            'computador': str(self.pc.pk),
            'horario_inicio': como_input(daqui_horas(4)),
            'horario_fim': como_input(daqui_horas(6)),
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_permite_agendamento_no_mesmo_horario_em_outro_computador(self):
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )
        form = AgendamentoForm({
            'computador': str(self.pc2.pk),
            'horario_inicio': como_input(daqui_horas(2)),
            'horario_fim': como_input(daqui_horas(4)),
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_agendamento_cancelado_libera_o_horario(self):
        """Soft delete precisa liberar o horário para novo agendamento."""
        cancelado = Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )
        cancelado.marcar_cancelado(self.dono)

        form = AgendamentoForm({
            'computador': str(self.pc.pk),
            'horario_inicio': como_input(daqui_horas(2)),
            'horario_fim': como_input(daqui_horas(4)),
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_mensagem_de_conflito_usa_horario_local(self):
        """Regressão: a mensagem exibia UTC (3h atrás em São Paulo)."""
        inicio = amanha_hora(13)
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=inicio, horario_fim=inicio + timedelta(hours=1),
        )
        form = AgendamentoForm({
            'computador': str(self.pc.pk),
            'horario_inicio': como_input(inicio + timedelta(minutes=10)),
            'horario_fim': como_input(inicio + timedelta(hours=2)),
        })
        self.assertFalse(form.is_valid())
        self.assertIn(inicio.strftime('%d/%m %H:%M'), str(form.errors))


# ---------------------------------------------------------------------------
# Concorrência (B3)
# ---------------------------------------------------------------------------

class TesteConcorrencia(TransactionTestCase):
    """Dois usuários reserva o MESMO horário ao mesmo tempo.

    Precisa de TransactionTestCase e de duas conexões reais: o lock
    `select_for_update()` do formulário só tem efeito entre transações
    concorrentes de verdade.
    """

    reset_sequences = True

    def setUp(self):
        self.pc = Computador.objects.create(nome='liaan-01', placa_de_video='RTX 4090')
        self.ana = User.objects.create_user('ana', password='senha-forte-123')
        self.bruno = User.objects.create_user('bruno', password='senha-forte-123')

    def dados(self):
        return {
            'computador': str(self.pc.pk),
            'horario_inicio': como_input(daqui_horas(2)),
            'horario_fim': como_input(daqui_horas(4)),
        }

    def test_segunda_reserva_concorrente_e_rejeitada(self):
        erros = []

        def reservar(user):
            # `close_old_connections` antes de abrir a transação concorrente e
            # `connection.close()` no fim: sem isso as threads mantêm sessões
            # abertas e o teardown do banco de teste falha.
            close_old_connections()
            try:
                form = AgendamentoForm(self.dados())
                if not form.is_valid():
                    erros.append(str(form.errors))
                    return
                try:
                    form.save(usuario=user)
                except ValidationError as erro:
                    erros.append(str(erro))
            finally:
                connection.close()

        t1 = threading.Thread(target=reservar, args=(self.ana,))
        t2 = threading.Thread(target=reservar, args=(self.bruno,))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # O teste SEMPRE reabre uma transação explícita. Sem isso o código do
        # teste rodaria dentro de um savepoint e o lock por linha não
        # serializaria as duas threads.
        with transaction.atomic():
            self.assertEqual(
                Agendamento.objects.filter(
                    computador=self.pc,
                    horario_inicio__lt=daqui_horas(4),
                    horario_fim__gt=daqui_horas(2),
                ).count(),
                1,
                f"Esperado 1 agendamento, erros: {erros}",
            )

        self.assertTrue(erros, 'A segunda reserva deveria ter sido rejeitada.')


# ---------------------------------------------------------------------------
# Integridade no banco
# ---------------------------------------------------------------------------
class TesteConstraintHorario(TesteBase):
    """O banco é a última linha de defesa contra horário invertido.

    Isso não é teórico: a view antiga não chamava as validações do ModelForm,
    então o banco de produção pode ter linhas com fim <= início. A migração
    0002 as cancela em vez de apagar, e a constraint só exige horário válido
    para reservas ATIVAS — o histórico cancelado fica preservado como está.
    """

    def test_agendamento_ativo_com_horario_invertido_e_recusado(self):
        with self.assertRaises(IntegrityError):
            Agendamento.objects.create(
                computador=self.pc, usuario=self.dono,
                horario_inicio=daqui_horas(4), horario_fim=daqui_horas(2),
            )

    def test_agendamento_ativo_com_duracao_zero_e_recusado(self):
        momento = daqui_horas(4)
        with self.assertRaises(IntegrityError):
            Agendamento.objects.create(
                computador=self.pc, usuario=self.dono,
                horario_inicio=momento, horario_fim=momento,
            )

    def test_cancelado_preserva_horario_invertido_do_historico(self):
        """Regressão: sem a exceção para cancelados, a migração 0002 quebra."""
        momento = daqui_horas(4)
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=momento, horario_fim=momento - timedelta(hours=1),
            cancelado=True, data_cancelamento=timezone.now(),
        )
        self.assertEqual(Agendamento.objects.filter(cancelado=True).count(), 1)


# ---------------------------------------------------------------------------
# Soft delete e permissão de exclusão
# ---------------------------------------------------------------------------
class TesteExclusao(TesteBase):
    def setUp(self):
        super().setUp()
        self.agendamento = Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )
        self.url = reverse('mapeamento:excluir', args=[self.agendamento.pk])

    def test_dono_pode_excluir(self):
        self.client.force_login(self.dono)
        resposta = self.client.post(self.url)

        self.assertRedirects(resposta, reverse('mapeamento:home'))
        self.agendamento.refresh_from_db()
        self.assertTrue(self.agendamento.cancelado)
        self.assertEqual(self.agendamento.cancelado_por, self.dono)
        self.assertIsNotNone(self.agendamento.data_cancelamento)
        # Soft delete: o registro continua no banco.
        self.assertTrue(Agendamento.objects.filter(pk=self.agendamento.pk).exists())

    def test_admin_pode_excluir_agendamento_de_outro(self):
        self.client.force_login(self.admin)
        resposta = self.client.post(self.url)

        self.assertEqual(resposta.status_code, 302)
        self.agendamento.refresh_from_db()
        self.assertTrue(self.agendamento.cancelado)

    def test_usuario_comum_nao_pode_excluir_agendamento_alheio(self):
        self.client.force_login(self.outro)
        resposta = self.client.post(self.url)

        self.assertEqual(resposta.status_code, 403)
        self.agendamento.refresh_from_db()
        self.assertFalse(self.agendamento.cancelado)

    def test_visitante_nao_pode_excluir(self):
        resposta = self.client.post(self.url)
        self.assertEqual(resposta.status_code, 302)  # redireciona para o login
        self.assertIn('/accounts/login/', resposta.url)

    def test_get_nao_exclui(self):
        """A rota é POST-only (CSRF / <img src> não pode apagar nada)."""
        self.client.force_login(self.dono)
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 405)
        self.agendamento.refresh_from_db()
        self.assertFalse(self.agendamento.cancelado)

    def test_excluir_duas_vezes_e_idempotente(self):
        self.client.force_login(self.dono)
        self.client.post(self.url)
        self.client.post(self.url)

        self.agendamento.refresh_from_db()
        self.assertTrue(self.agendamento.cancelado)

    def test_dono_exclui_agendamento_em_andamento(self):
        """Regra definida: em andamento o dono também pode excluir."""
        em_andamento = Agendamento.objects.create(
            computador=self.pc2, usuario=self.dono,
            horario_inicio=daqui_horas(-1), horario_fim=daqui_horas(1),
        )
        self.client.force_login(self.dono)
        resposta = self.client.post(reverse('mapeamento:excluir', args=[em_andamento.pk]))

        self.assertEqual(resposta.status_code, 302)
        em_andamento.refresh_from_db()
        self.assertTrue(em_andamento.cancelado)

    def test_ajax_devolve_json(self):
        self.client.force_login(self.dono)
        resposta = self.client.post(
            self.url, headers={'x-requested-with': 'XMLHttpRequest'}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('versao', resposta.json())

    def test_ajax_negado_devolve_403(self):
        self.client.force_login(self.outro)
        resposta = self.client.post(
            self.url, headers={'x-requested-with': 'XMLHttpRequest'}
        )
        self.assertEqual(resposta.status_code, 403)

    def test_regra_centralizada_no_modelo(self):
        self.assertTrue(self.agendamento.pode_excluir(self.dono))
        self.assertTrue(self.agendamento.pode_excluir(self.admin))
        self.assertFalse(self.agendamento.pode_excluir(self.outro))

    def test_apagar_usuario_com_agendamento_e_bloqueado(self):
        """on_delete=PROTECT preserva o histórico do laboratório."""
        with self.assertRaises(Exception):
            self.dono.delete()


# ---------------------------------------------------------------------------
# Status efetivo
# ---------------------------------------------------------------------------

class TesteStatus(TesteBase):
    def test_disponivel_sem_agendamento(self):
        self.assertEqual(calcular_status(self.pc, []), STATUS_DISPONIVEL)

    def test_ocupado_durante_agendamento(self):
        agendamento = Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(-1), horario_fim=daqui_horas(1),
        )
        self.assertEqual(calcular_status(self.pc, [agendamento]), STATUS_OCUPADO)

    def test_disponivel_fora_do_agendamento(self):
        agendamento = Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )
        self.assertEqual(calcular_status(self.pc, [agendamento]), STATUS_DISPONIVEL)

    def test_manutencao_vence_sobre_ocupado(self):
        self.pc.status = STATUS_MANUTENCAO
        agendamento = Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(-1), horario_fim=daqui_horas(1),
        )
        self.assertEqual(calcular_status(self.pc, [agendamento]), STATUS_MANUTENCAO)

    def test_status_nao_e_gravado_no_banco(self):
        """Regressão do bug em que 'Ocupado' virava valor persistido."""
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(-1), horario_fim=daqui_horas(1),
        )
        self.client.force_login(self.dono)
        self.client.get(reverse('mapeamento:home'))

        self.pc.refresh_from_db()
        self.assertEqual(self.pc.status, STATUS_DISPONIVEL)

    def test_pagina_mostra_status_calculado(self):
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(-1), horario_fim=daqui_horas(1),
        )
        self.client.force_login(self.dono)
        resposta = self.client.get(reverse('mapeamento:home'))

        self.assertContains(resposta, 'data-pc-id="%s"' % self.pc.pk)
        self.assertContains(resposta, 'data-status="O"')
        self.assertContains(resposta, 'Ocupado')


# ---------------------------------------------------------------------------
# Horários disponíveis
# ---------------------------------------------------------------------------

class TesteHorariosDisponiveis(TesteBase):
    def url(self, **params):
        base = {'data': timezone.localtime().strftime('%Y-%m-%d'), 'computador_id': str(self.pc.pk)}
        base.update(params)
        return '/agendamento/horarios_disponiveis/?' + '&'.join(
            f'{k}={v}' for k, v in base.items()
        )

    def test_agora(self):
        self.client.force_login(self.dono)
        resposta = self.client.get(self.url())
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('pontos', resposta.json())

    def test_nao_oferece_passado(self):
        ontem = (timezone.localtime() - timedelta(days=1)).strftime('%Y-%m-%d')
        self.client.force_login(self.dono)
        resposta = self.client.get(self.url(data=ontem))
        self.assertEqual(resposta.json()['pontos'], [])

    def test_nao_oferece_00h_do_dia_seguinte(self):
        """B4/B14: o dia precisa terminar antes da meia-noite seguinte."""
        amanha = (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%d')
        self.client.force_login(self.dono)
        pontos = self.client.get(self.url(data=amanha)).json()['pontos']

        self.assertTrue(pontos)
        for ponto in pontos:
            self.assertTrue(ponto['value'].startswith(amanha), ponto['value'])

    def test_remove_horarios_ocupados(self):
        """B4: o endpoint precisa realmente filtrar por computador."""
        amanha = (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%d')
        inicio = amanha_hora(15)
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=inicio, horario_fim=inicio + timedelta(hours=1),
        )

        self.client.force_login(self.dono)
        pontos = self.client.get(self.url(data=amanha)).json()['pontos']
        valores = {p['value'] for p in pontos}

        self.assertNotIn(como_input(inicio), valores)

    def test_horarios_ocupados_de_outro_computador_nao_afetam(self):
        amanha = (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%d')
        inicio = amanha_hora(15)
        Agendamento.objects.create(
            computador=self.pc2, usuario=self.dono,
            horario_inicio=inicio, horario_fim=inicio + timedelta(hours=1),
        )

        self.client.force_login(self.dono)
        pontos = self.client.get(self.url(data=amanha)).json()['pontos']

        self.assertIn(como_input(inicio), {p['value'] for p in pontos})

    def test_ignora_agendamento_cancelado(self):
        amanha = (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%d')
        inicio = amanha_hora(15)
        cancelado = Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=inicio, horario_fim=inicio + timedelta(hours=1),
        )
        cancelado.marcar_cancelado(self.dono)

        self.client.force_login(self.dono)
        pontos = self.client.get(self.url(data=amanha)).json()['pontos']

        self.assertIn(como_input(inicio), {p['value'] for p in pontos})

    def test_inicio_exato_de_agendamento_existente_fica_bloqueado(self):
        """Regressão: o slot que coincide com o INÍCIO de uma reserva precisa
        estar bloqueado. Testar só o instante o tratava como livre."""
        amanha = (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%d')
        inicio = amanha_hora(15)
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=inicio, horario_fim=inicio + timedelta(hours=1),
        )

        self.client.force_login(self.dono)
        pontos = self.client.get(self.url(data=amanha)).json()['pontos']
        valores = {p['value'] for p in pontos}

        self.assertNotIn(como_input(inicio), valores)
        # ...enquanto o horário imediatamente anterior à reserva continua livre.
        self.assertIn(como_input(inicio - timedelta(minutes=INTERVALO_MINUTOS)), valores)

    def test_filtra_por_horario_de_inicio(self):
        """Com `inicio=`, só volta o que estiver estritamente depois."""
        amanha = (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%d')
        inicio = amanha_hora(15)

        self.client.force_login(self.dono)
        pontos = self.client.get(self.url(data=amanha, inicio=como_input(inicio))).json()['pontos']
        valores = {p['value'] for p in pontos}

        self.assertTrue(valores)
        self.assertNotIn(como_input(inicio), valores)
        for valor in valores:
            self.assertGreater(valor, como_input(inicio))

    def test_exige_autenticacao(self):
        resposta = self.client.get(self.url())
        self.assertEqual(resposta.status_code, 302)

    def test_parametros_invalidos(self):
        self.client.force_login(self.dono)
        self.assertEqual(self.client.get(self.url(data='xx-xx-xx')).status_code, 400)
        self.assertEqual(self.client.get(self.url(computador_id='9999')).status_code, 400)


# ---------------------------------------------------------------------------
# Tempo real (polling + ETag)
# ---------------------------------------------------------------------------

class TesteEstadoJson(TesteBase):
    def setUp(self):
        super().setUp()
        self.url = reverse('mapeamento:estado')

    def test_exige_autenticacao(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_snapshot_inicial(self):
        self.client.force_login(self.dono)
        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertIn('versao', dados)
        self.assertEqual(len(dados['computadores']), 2)
        self.assertIn('ETag', resposta.headers)

    def test_304_quando_nada_muda(self):
        self.client.force_login(self.dono)
        primeira = self.client.get(self.url)
        etag = primeira.headers['ETag']

        segunda = self.client.get(self.url, headers={'if-none-match': etag})
        self.assertEqual(segunda.status_code, 304)
        self.assertEqual(segunda.content, b'')

    def test_304_invalido_apos_novo_agendamento(self):
        self.client.force_login(self.dono)
        etag = self.client.get(self.url).headers['ETag']

        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )

        resposta = self.client.get(self.url, headers={'if-none-match': etag})
        self.assertEqual(resposta.status_code, 200)

    def test_304_invalido_apos_cancelamento(self):
        agendamento = Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )
        self.client.force_login(self.dono)
        etag = self.client.get(self.url).headers['ETag']

        agendamento.marcar_cancelado(self.dono)

        resposta = self.client.get(self.url, headers={'if-none-match': etag})
        self.assertEqual(resposta.status_code, 200)

    def test_etag_diferente_por_usuario(self):
        """Regressão: `pode_excluir` é dependente do usuário, então o ETag
        não pode ser o mesmo para todos."""
        self.client.force_login(self.dono)
        etag_dono = self.client.get(self.url).headers['ETag']

        self.client.force_login(self.admin)
        etag_admin = self.client.get(self.url).headers['ETag']

        self.assertNotEqual(etag_dono, etag_admin)

    def test_permissao_expor_por_usuario(self):
        agendamento = Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )

        self.client.force_login(self.dono)
        cards = self.client.get(self.url).json()['computadores']
        item = cards[0]['agendamentos'][0]
        self.assertTrue(item['pode_excluir'])

        self.client.force_login(self.outro)
        cards = self.client.get(self.url).json()['computadores']
        item = cards[0]['agendamentos'][0]
        self.assertFalse(item['pode_excluir'])

    def test_nao_expoe_agendamento_cancelado(self):
        agendamento = Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )
        agendamento.marcar_cancelado(self.dono)

        self.client.force_login(self.dono)
        cards = self.client.get(self.url).json()['computadores']
        self.assertEqual(cards[0]['agendamentos'], [])

    def test_agendamento_em_andamento_marca_ocupado(self):
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(-1), horario_fim=daqui_horas(1),
        )
        self.client.force_login(self.dono)
        cards = self.client.get(self.url).json()['computadores']

        card_pc = next(c for c in cards if c['id'] == self.pc.pk)
        card_pc2 = next(c for c in cards if c['id'] == self.pc2.pk)
        self.assertEqual(card_pc['status'], STATUS_OCUPADO)
        self.assertEqual(card_pc['rotulo'], 'Ocupado')
        self.assertEqual(card_pc2['status'], STATUS_DISPONIVEL)

    def test_agendamento_futuro_nao_marca_ocupado(self):
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )
        self.client.force_login(self.dono)
        cards = self.client.get(self.url).json()['computadores']

        card_pc = next(c for c in cards if c['id'] == self.pc.pk)
        self.assertEqual(card_pc['status'], STATUS_DISPONIVEL)
        # ...mas ele continua listado para todos verem.
        self.assertEqual(len(card_pc['agendamentos']), 1)

    def test_manutencao_vence_no_json(self):
        self.pc.status = STATUS_MANUTENCAO
        self.pc.save()
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(-1), horario_fim=daqui_horas(1),
        )
        self.client.force_login(self.dono)
        cards = self.client.get(self.url).json()['computadores']

        card_pc = next(c for c in cards if c['id'] == self.pc.pk)
        self.assertEqual(card_pc['status'], STATUS_MANUTENCAO)
        self.assertTrue(card_pc['em_manutencao'])


# ---------------------------------------------------------------------------
# Criação via view
# ---------------------------------------------------------------------------

class TesteViewAgendar(TesteBase):
    def setUp(self):
        super().setUp()
        self.url = reverse('mapeamento:agendar')

    def dados(self, **extra):
        dados = {
            'computador': str(self.pc.pk),
            'horario_inicio': como_input(daqui_horas(2)),
            'horario_fim': como_input(daqui_horas(4)),
        }
        dados.update(extra)
        return dados

    def test_cria_e_redireciona(self):
        self.client.force_login(self.dono)
        resposta = self.client.post(self.url, self.dados())

        self.assertRedirects(resposta, reverse('mapeamento:home'))
        self.assertEqual(Agendamento.objects.ativos().count(), 1)

    def test_conflito_nao_reabre_a_pagina_com_modal(self):
        """Regressão: antes o erro redirigia e o modal abria em branco."""
        Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )
        self.client.force_login(self.dono)
        resposta = self.client.post(self.url, self.dados())

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'data-modal-aberto="1"')
        self.assertContains(resposta, 'data-pc-id="%s"' % self.pc.pk)
        self.assertEqual(Agendamento.objects.ativos().count(), 1)

    def test_nao_vaza_detalhe_tecnico_da_excecao(self):
        """Regressão: a view expunha str(e) para o usuário."""
        self.client.force_login(self.dono)
        resposta = self.client.post(self.url, self.dados(horario_inicio='nao-e-data'))

        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertNotIn('Traceback', conteudo)
        self.assertNotIn('fromisoformat', conteudo)

    def test_get_redireciona(self):
        self.client.force_login(self.dono)
        resposta = self.client.get(self.url)
        self.assertRedirects(resposta, reverse('mapeamento:home'))


class TesteTemplatePainel(TesteBase):
    """O HTML precisa refletir a mesma regra de permissão do back-end."""

    def setUp(self):
        super().setUp()
        self.agendamento = Agendamento.objects.create(
            computador=self.pc, usuario=self.dono,
            horario_inicio=daqui_horas(2), horario_fim=daqui_horas(4),
        )

    def test_dono_ve_o_botao_excluir(self):
        self.client.force_login(self.dono)
        html = self.client.get(reverse('mapeamento:home')).content.decode()

        self.assertIn('btn-excluir-agendamento', html)
        self.assertIn(
            reverse('mapeamento:excluir', args=[self.agendamento.pk]), html
        )

    def test_admin_ve_o_botao_excluir(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('mapeamento:home')).content.decode()
        self.assertIn('btn-excluir-agendamento', html)

    def test_terceiro_nao_ve_o_botao_excluir(self):
        self.client.force_login(self.outro)
        html = self.client.get(reverse('mapeamento:home')).content.decode()

        self.assertNotIn('btn-excluir-agendamento', html)

    def test_form_de_exclusao_usa_um_unico_token_csrf(self):
        """Um form compartilhado, não um token por agendamento."""
        self.client.force_login(self.dono)
        html = self.client.get(reverse('mapeamento:home')).content.decode()

        self.assertEqual(html.count('id="form-excluir"'), 1)
        # 1 (form de exclusão) + 1 (form do modal de agendamento) + 1 (logout)
        self.assertEqual(html.count('csrfmiddlewaretoken'), 3)

    def test_pagina_nao_expoe_agendamento_cancelado(self):
        self.agendamento.marcar_cancelado(self.dono)
        self.client.force_login(self.dono)
        html = self.client.get(reverse('mapeamento:home')).content.decode()

        self.assertIn('Livre de agendamentos.', html)
        self.assertNotIn('btn-excluir-agendamento', html)


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------

class TesteLogin(TesteBase):
    def setUp(self):
        super().setUp()
        self.url = reverse('login')
        cache.clear()

    def test_usuario_ativo_entra(self):
        resposta = self.client.post(self.url, {'username': 'ana', 'password': 'senha-forte-123'})
        self.assertEqual(resposta.status_code, 302)

    def test_usuario_inativo_nao_entra(self):
        inativo = User.objects.create_user('pendente', password='senha-forte-123', is_active=False)
        resposta = self.client.post(self.url, {'username': 'pendente', 'password': 'senha-forte-123'})

        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_senha_errada_nao_entra(self):
        resposta = self.client.post(self.url, {'username': 'ana', 'password': 'errada'})
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_mensagem_nao_permite_enumerar_usuarios(self):
        """Conta inexistente e conta inativa devem gerar o mesmo texto."""
        User.objects.create_user('pendente', password='x', is_active=False)

        r1 = self.client.post(self.url, {'username': 'inexistente', 'password': 'x'})
        r2 = self.client.post(self.url, {'username': 'pendente', 'password': 'x'})

        m1 = [e for e in r1.context['form'].non_field_errors()]
        m2 = [e for e in r2.context['form'].non_field_errors()]
        self.assertEqual(m1, m2)


class TesteLogout(TesteBase):
    def test_logout_requer_post(self):
        self.client.force_login(self.dono)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)

    def test_logout_encerra_a_sessao(self):
        self.client.force_login(self.dono)
        resposta = self.client.post(reverse('logout'))

        self.assertEqual(resposta.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)
