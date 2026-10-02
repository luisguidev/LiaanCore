"""Testes do app Mapeamento.

Cobrem as regras de negócio que antes não tinham nenhum teste:
conflito de horário, soft delete, permissão de exclusão, cálculo de status,
filtro de horários livres e o contrato de ETag do polling.
"""

import os
import subprocess
import sys
import threading
from pathlib import Path
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from .forms import AgendamentoForm
from .models import Agendamento, Computador, TentativaRateLimit
from .ratelimit import (
    chave_login,
    client_ip,
    excedeu_limite,
    inicio_da_janela,
    limpar_tudo,
)
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
        limpar_tudo()
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
        limpar_tudo()

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


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
class TesteRateLimit(TesteBase):
    """O limite de tentativas no login e no cadastro.

    Antes o contador vivia no cache LocMem, que é POR PROCESSO: com mais de um
    worker do Gunicorn cada um contava separado. Agora ele está no Postgres e o
    incremento é atômico.
    """

    JANELA = 300
    MAXIMO = 3

    def setUp(self):
        super().setUp()
        self.url = reverse('login')

    def conta(self, vezes):
        return [excedeu_limite('login:1.2.3.4', self.JANELA, self.MAXIMO) for _ in range(vezes)]

    def test_permite_ate_o_maximo_e_bloqueia_a_seguinte(self):
        bloqueios = self.conta(self.MAXIMO + 2)
        self.assertEqual(bloqueios, [False] * self.MAXIMO + [True, True])

    def test_bloqueio_acumula_um_contador_na_janela(self):
        self.conta(self.MAXIMO)
        registro = TentativaRateLimit.objects.get(chave='login:1.2.3.4')
        self.assertEqual(registro.contagem, self.MAXIMO)

    def test_chaves_diferentes_nao_se_interferem(self):
        """Cadastro e login, ou IPs diferentes, têm contadores separados."""
        for _ in range(self.MAXIMO):
            excedeu_limite('login:1.2.3.4', self.JANELA, self.MAXIMO)

        self.assertFalse(excedeu_limite('cadastro:1.2.3.4', self.JANELA, self.MAXIMO))
        self.assertFalse(excedeu_limite('login:5.6.7.8', self.JANELA, self.MAXIMO))

    def test_janela_que_vence_zera_o_contador(self):
        """Passada a janela, a conta começa de novo."""
        for _ in range(self.MAXIMO + 1):
            excedeu_limite('login:1.2.3.4', self.JANELA, self.MAXIMO)
        self.assertTrue(excedeu_limite('login:1.2.3.4', self.JANELA, self.MAXIMO))

        # Avança o relógio para o bloco de janela seguinte.
        with patch('Mapeamento.ratelimit.timezone.now',
                   return_value=timezone.now() + timezone.timedelta(seconds=self.JANELA)):
            self.assertFalse(excedeu_limite('login:1.2.3.4', self.JANELA, self.MAXIMO))

        self.assertEqual(TentativaRateLimit.objects.filter(chave='login:1.2.3.4').count(), 2)

    def test_contador_esta_no_banco_e_nao_por_processo(self):
        """Regressão do motivo da mudança: o estado é compartilhável."""
        excedeu_limite('login:1.2.3.4', self.JANELA, self.MAXIMO)
        # Um "outro worker" é só outra consulta ao mesmo banco.
        self.assertEqual(
            TentativaRateLimit.objects.filter(chave='login:1.2.3.4').count(), 1
        )

    def test_login_real_bloqueia_apos_o_limite(self):
        """Integração: a view de login usa o mesmo limite."""
        from django.conf import settings

        janela, _maximo = settings.RATE_LIMIT_LOGIN
        # Limite baixo para o teste não precisar de 10 tentativas.
        with self.settings(RATE_LIMIT_LOGIN=(janela, 2)):
            for _ in range(2):
                self.client.post(self.url, {'username': 'ana', 'password': 'errada'})

            resposta = self.client.post(self.url, {'username': 'ana', 'password': 'errada'})

        self.assertEqual(resposta.status_code, 200)
        self.assertIn('Muitas tentativas', resposta.content.decode())


class TesteRateLimitConcorrencia(TransactionTestCase):
    """O incremento atômico do rate limit sob concorrência real.

    Precisa de TransactionTestCase: num TestCase comum tudo roda dentro de uma
    transação que não é commitada, e as threads — que usam conexões próprias —
    não enxergariam as linhas. Aqui os dados são commitados de verdade.
    """

    JANELA = 300
    MAXIMO = 1000
    THREADS = 4
    POR_THREAD = 10

    def test_incremento_nao_se_perde(self):
        """O padrão ler -> gravar perderia incrementos; o UPDATE atômico não."""
        resultados = []
        trava = threading.Lock()

        def registrar():
            # Sem close_old_connections as threads seguram sessão aberta e o
            # teardown do banco de teste falha (mesmo cuidado do outro teste
            # de concorrência deste arquivo).
            close_old_connections()
            try:
                for _ in range(self.POR_THREAD):
                    excedeu = excedeu_limite('login:9.9.9.9', self.JANELA, self.MAXIMO)
                    with trava:
                        resultados.append(excedeu)
            finally:
                connection.close()

        threads = [threading.Thread(target=registrar) for _ in range(self.THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Reabre uma transação explícita: fora dela o código do teste roda
        # dentro de um savepoint e não vê o que as threads commitaram.
        with transaction.atomic():
            registro = TentativaRateLimit.objects.get(chave='login:9.9.9.9')
            self.assertEqual(
                registro.contagem,
                self.THREADS * self.POR_THREAD,
                'contagem perdida: só '
                f'{registro.contagem} de {self.THREADS * self.POR_THREAD} tentativas contadas',
            )
            self.assertEqual(len(resultados), self.THREADS * self.POR_THREAD)
            self.assertFalse(any(resultados))

    def test_nenhuma_linha_duplicada_por_chave_e_janela(self):
        """A UniqueConstraint impede duas linhas para a mesma janela."""
        close_old_connections()
        try:
            for _ in range(5):
                excedeu_limite('login:8.8.8.8', self.JANELA, self.MAXIMO)
        finally:
            connection.close()

        with transaction.atomic():
            self.assertEqual(
                TentativaRateLimit.objects.filter(chave='login:8.8.8.8').count(), 1
            )


class TesteComandosRateLimit(TesteBase):
    """Os comandos de manutenção do contador."""

    def test_limpar_rate_limit_apaga_so_as_vencidas(self):
        antiga = TentativaRateLimit.objects.create(
            chave='login:1.1.1.1',
            janela_inicio=timezone.now() - timedelta(days=2),
            contagem=9,
        )
        atual = TentativaRateLimit.objects.create(
            chave='login:1.1.1.1',
            janela_inicio=inicio_da_janela(300),
            contagem=1,
        )

        saida = StringIO()
        call_command('limpar_rate_limit', stdout=saida)

        self.assertFalse(TentativaRateLimit.objects.filter(pk=antiga.pk).exists())
        self.assertTrue(TentativaRateLimit.objects.filter(pk=atual.pk).exists())

    def test_limpar_rate_limit_tudo_zera(self):
        TentativaRateLimit.objects.create(
            chave='login:2.2.2.2',
            janela_inicio=inicio_da_janela(300),
            contagem=1,
        )

        saida = StringIO()
        call_command('limpar_rate_limit', '--tudo', stdout=saida)

        self.assertEqual(TentativaRateLimit.objects.count(), 0)

    def test_simulador_exige_dois_dispositivos(self):
        """Com um dispositivo não há o que observar, e ele nem deve tocar no banco."""
        saida, erro = StringIO(), StringIO()
        # O runner de teste roda com DEBUG=0, o que dispara a trava de
        # segurança do comando; aqui ela só atrapalharia o que se quer testar.
        call_command('simular_dispositivos', '--dispositivos', '1',
                     '--permitir-producao', stdout=saida, stderr=erro)

        self.assertIn('pelo menos 2', erro.getvalue())
        self.assertEqual(TentativaRateLimit.objects.count(), 0)

    def test_simulador_avisa_quando_nao_ha_computador(self):
        Computador.objects.all().delete()

        erro = StringIO()
        call_command('simular_dispositivos', '--dispositivos', '2',
                     '--permitir-producao', stderr=erro)

        self.assertIn('loaddata', erro.getvalue())


class TesteTravaDoSimulador(TesteBase):
    """O simulador não pode criar contas ativas em produção.

    Os usuários `disp1..N` nascem com `is_active=True` e a senha padrão, que
    está escrita no código do comando — logo, publicada no repositório. Se
    ele rodasse contra produção deixaria um backdoor com senha conhecida.
    """

    def _roda(self, **flags):
        """Chama o comando. As flags chegam como `--permitir-producao=True`."""
        erro = StringIO()
        args = ['--dispositivos', '2', '--espera', '1']
        for flag, valor in flags.items():
            if valor is True:
                args.append(flag)
            else:
                args.extend([flag, valor])

        call_command('simular_dispositivos', *args, stdout=StringIO(), stderr=erro)
        return erro.getvalue()

    def test_recusa_com_debug_desligado(self):
        """O runner de teste tem DEBUG=0, que é exatamente o caso de risco."""
        self.assertFalse(settings.DEBUG)

        erro = self._roda()

        self.assertIn('Recusando rodar', erro)
        self.assertIn('DEBUG=0', erro)
        self.assertFalse(User.objects.filter(username__startswith='disp').exists())

    def test_recusa_contra_host_de_producao(self):
        erro = self._roda(**{'--url': 'https://liaancore.onrender.com'})

        self.assertIn('Recusando rodar', erro)
        self.assertIn('não é localhost', erro)
        self.assertFalse(User.objects.filter(username__startswith='disp').exists())

    def test_permitir_producao_passa_da_trava(self):
        erro = self._roda(**{'--permitir-producao': True})

        self.assertNotIn('Recusando rodar', erro)
        self.assertIn('--permitir-producao informado', erro)

    def test_trava_cita_a_senha_publicada(self):
        """A mensagem precisa dizer o risco, não só recusar."""
        erro = self._roda()

        self.assertIn('senha fixa', erro)
        self.assertIn('--permitir-producao', erro)


class TesteSegurancaProducao(TestCase):
    """Configuração que o Django exige para subir em produção.

    Estes testes rodam um interpretador separado porque a validação acontece
    na importação do settings: dentro do processo de teste já é tarde demais.
    """

    RAIZ = Path(__file__).resolve().parent.parent

    def _subprocess(self, ambiente_extra):
        return subprocess.run(
            [sys.executable, '-c', 'import django; django.setup()'],
            cwd=self.RAIZ,
            env=dict(os.environ, **ambiente_extra),
            capture_output=True,
            text=True,
        )

    def test_producao_sem_secret_key_recusa_subir(self):
        resultado = self._subprocess({'DEBUG': '0', 'SECRET_KEY': ''})

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn('SECRET_KEY', resultado.stderr)

    def test_producao_com_secret_key_sobe(self):
        resultado = self._subprocess({
            'DEBUG': '0',
            'SECRET_KEY': 'x' * 60,
            'RENDER_EXTERNAL_URL': 'https://liaancore.onrender.com',
        })

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_desenvolvimento_sem_secret_key_sobe(self):
        """Sem isso o projeto local não subiria sem configurar nada."""
        resultado = self._subprocess({'DEBUG': '1', 'SECRET_KEY': ''})

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_producao_sem_host_defined_recusa_subir(self):
        """O curinga '.onrender.com' saiu: sem host, não sobe.

        Aceitar qualquer subdomínio do Render deixaria o cabeçalho Host ser
        forjado por quem não é o dono do serviço.
        """
        resultado = self._subprocess({
            'DEBUG': '0',
            'SECRET_KEY': 'x' * 60,
            'ALLOWED_HOSTS': '',
            'RENDER_EXTERNAL_URL': '',
        })

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn('ALLOWED_HOSTS', resultado.stderr)

    def test_allowed_hosts_usa_o_host_do_render(self):
        """Com RENDER_EXTERNAL_URL, o host cai no ALLOWED_HOSTS sem curinga.

        Roda num interpretador separado de propósito: recarregar o módulo de
        settings dentro do processo de teste deixaria DEBUG=0 e o storage de
        estáticos de produção valendo para todos os testes seguintes.
        """
        resultado = self._subprocess_printando({
            'DEBUG': '0',
            'SECRET_KEY': 'x' * 60,
            'ALLOWED_HOSTS': '',
            'RENDER_EXTERNAL_URL': 'https://liaancore.onrender.com/algum/caminho',
        })

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        hosts = resultado.stdout.strip().split(',')
        self.assertIn('liaancore.onrender.com', hosts)
        # O ponto do teste: o curinga não pode estar lá. Comparando a lista
        # inteira, porque 'liaancore.onrender.com' CONTÉM a string
        # '.onrender.com' e a checagem por substring daria falso positivo.
        self.assertNotIn('.onrender.com', hosts)

    def _subprocess_printando(self, ambiente_extra):
        """Sobe o Django num interpretador separado e imprime ALLOWED_HOSTS."""
        return subprocess.run(
            [
                sys.executable, '-c',
                'import django; django.setup();'
                ' from django.conf import settings;'
                ' print(",".join(settings.ALLOWED_HOSTS))',
            ],
            cwd=self.RAIZ,
            env=dict(os.environ, **ambiente_extra),
            capture_output=True,
            text=True,
        )


class TesteIpConfiavel(TestCase):
    """De qual header o rate limit tira o IP do cliente.

    O Render NÃO documenta se o proxy reescreve ou apenas anexa o
    X-Forwarded-For (a resposta do suporte e um relato em campo discordam).
    Por isso o código não aposta numa das leituras: ele prefere os headers
    que a borda SOBRESCREVE e mantém o XFF como último recurso.
    """

    def _request(self, **meta):
        return RequestFactory().get('/', **meta)

    def test_true_client_ip_tem_precedencia(self):
        request = self._request(
            HTTP_TRUE_CLIENT_IP='9.9.9.9',
            HTTP_X_FORWARDED_FOR='1.1.1.1, 2.2.2.2',
        )
        self.assertEqual(client_ip(request), '9.9.9.9')

    def test_cf_connecting_ip_tem_precedencia(self):
        request = self._request(
            HTTP_CF_CONNECTING_IP='8.8.8.8',
            HTTP_X_FORWARDED_FOR='1.1.1.1',
        )
        self.assertEqual(client_ip(request), '8.8.8.8')

    def test_cai_para_o_xff_quando_nao_ha_header_confiavel(self):
        request = self._request(HTTP_X_FORWARDED_FOR='1.1.1.1, 2.2.2.2')
        self.assertEqual(client_ip(request), '1.1.1.1')

    def test_cai_para_remote_addr_sem_nenhum_header(self):
        request = self._request(REMOTE_ADDR='127.0.0.1')
        self.assertEqual(client_ip(request), '127.0.0.1')

    def test_header_confiavel_vazio_cai_para_o_xff(self):
        request = self._request(
            HTTP_TRUE_CLIENT_IP='   ',
            HTTP_X_FORWARDED_FOR='3.3.3.3',
        )
        self.assertEqual(client_ip(request), '3.3.3.3')


class TesteRateLimitPorUsuario(TesteBase):
    """O limite que independe de IP.

    Girar o IP (ou forjar o X-Forwarded-For) não pode acabar com a proteção:
    o contador por usuário existe para fechar a força bruta mesmo quando o
    atacante escolhe o IP de cada requisição.
    """

    def setUp(self):
        super().setUp()
        self.url = reverse('login')

    def test_chave_login_normaliza_o_nome(self):
        self.assertEqual(chave_login('  Ana  '), 'login-user:ana')
        self.assertEqual(chave_login('ANA'), chave_login('ana'))

    def test_limite_por_usuario_bloqueia_o_ataque(self):
        from django.conf import settings

        janela, _ = settings.RATE_LIMIT_LOGIN_POR_USUARIO
        with self.settings(
            RATE_LIMIT_LOGIN=(3600, 9999),      # o limite de IP não atrapalha
            RATE_LIMIT_LOGIN_POR_USUARIO=(janela, 3),
        ):
            for _ in range(3):
                self.client.post(self.url, {'username': 'ana', 'password': 'errada'})

            resposta = self.client.post(self.url, {'username': 'ana', 'password': 'errada'})

        self.assertEqual(resposta.status_code, 200)
        self.assertIn('Muitas tentativas para esta conta', resposta.content.decode())

    def test_trocar_de_ip_nao_escapa_do_limite(self):
        """O coração da correção: cada tentativa vem de um IP diferente."""
        from django.conf import settings

        janela, _ = settings.RATE_LIMIT_LOGIN_POR_USUARIO
        with self.settings(
            RATE_LIMIT_LOGIN=(3600, 9999),
            RATE_LIMIT_LOGIN_POR_USUARIO=(janela, 3),
        ):
            for tentativa in range(4):
                self.client.post(
                    self.url,
                    {'username': 'ana', 'password': 'errada'},
                    HTTP_X_FORWARDED_FOR=f'10.0.0.{tentativa}',
                )

            bloqueio = self.client.post(
                self.url,
                {'username': 'ana', 'password': 'errada'},
                HTTP_X_FORWARDED_FOR='10.0.0.99',
            )

        self.assertIn('Muitas tentativas para esta conta', bloqueio.content.decode())

    def test_limite_de_uma_conta_nao_atinge_a_outra(self):
        from django.conf import settings

        janela, _ = settings.RATE_LIMIT_LOGIN_POR_USUARIO
        with self.settings(
            RATE_LIMIT_LOGIN=(3600, 9999),
            RATE_LIMIT_LOGIN_POR_USUARIO=(janela, 3),
        ):
            for _ in range(5):
                self.client.post(self.url, {'username': 'ana', 'password': 'errada'})

            outra = self.client.post(self.url, {'username': 'bruno', 'password': 'errada'})

        self.assertNotIn('Muitas tentativas para esta conta', outra.content.decode())


class TesteRateLimitAdmin(TesteBase):
    """O painel administrativo também precisa de limite.

    O CustomAuthForm só cobre /accounts/login/. O /admin/login/ usa o
    AdminAuthenticationForm do Django, que não limita nada — e quem controla
    o superuser controla o laboratório inteiro.
    """

    def setUp(self):
        super().setUp()
        self.url = reverse('admin:login')
        self.admin = User.objects.create_superuser('chefe', 'chefe@lab.org', 'senha-forte-123')
        limpar_tudo()

    def test_login_do_admin_continua_funcionando(self):
        resposta = self.client.post(self.url, {'username': 'chefe', 'password': 'senha-forte-123'})
        self.assertEqual(resposta.status_code, 302)

    def test_admin_bloqueia_apos_o_limite(self):
        from django.conf import settings

        janela, _ = settings.RATE_LIMIT_LOGIN_ADMIN
        with self.settings(RATE_LIMIT_LOGIN_ADMIN=(janela, 3)):
            for _ in range(3):
                self.client.post(self.url, {'username': 'chefe', 'password': 'errada'})

            resposta = self.client.post(self.url, {'username': 'chefe', 'password': 'errada'})

        self.assertEqual(resposta.status_code, 429)
        self.assertIn('Muitas tentativas de acesso ao painel', resposta.content.decode())

    def test_admin_bloqueia_mesmo_com_a_senha_correta(self):
        """O limite conta tentativas, não falhas.

        Se contasse só os erros, o próprio limite viraria o que impede o
        ataque: o atacante erra N vezes e aí acerta a senha.
        """
        from django.conf import settings

        janela, _ = settings.RATE_LIMIT_LOGIN_ADMIN
        with self.settings(RATE_LIMIT_LOGIN_ADMIN=(janela, 3)):
            for _ in range(3):
                self.client.post(self.url, {'username': 'chefe', 'password': 'errada'})

            resposta = self.client.post(self.url, {'username': 'chefe', 'password': 'senha-forte-123'})

        self.assertEqual(resposta.status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_admin_ainda_renderiza_o_formulario(self):
        """Responder 429 com um corpo quebrado seria pior que não responder."""
        from django.conf import settings

        janela, _ = settings.RATE_LIMIT_LOGIN_ADMIN
        with self.settings(RATE_LIMIT_LOGIN_ADMIN=(janela, 1)):
            self.client.post(self.url, {'username': 'chefe', 'password': 'errada'})
            resposta = self.client.post(self.url, {'username': 'chefe', 'password': 'errada'})

        html = resposta.content.decode()
        self.assertEqual(resposta.status_code, 429)
        self.assertIn('csrfmiddlewaretoken', html)
        self.assertIn('id_username', html)
        # A mensagem de bloqueio aparece sem revelar se a conta existe.
        self.assertNotIn('chefe', html.split('csrfmiddlewaretoken')[0])
