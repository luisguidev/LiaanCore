"""Cálculo do status efetivo de um computador.

O campo `Computador.status` guarda apenas o estado MANUAL do equipamento
(Disponível / Manutenção). "Ocupado" nunca é gravado no banco: ele é sempre
derivado dos agendamentos em andamento.

Centralizar o cálculo aqui garante que a página (lista_computadores) e o
endpoint JSON de tempo real (estado_json) mostrem exatamente o mesmo status.
"""

from django.utils import timezone

STATUS_DISPONIVEL = 'D'
STATUS_MANUTENCAO = 'M'
STATUS_OCUPADO = 'O'

ROTULOS = {
    STATUS_DISPONIVEL: 'Disponível',
    STATUS_MANUTENCAO: 'Manutenção',
    STATUS_OCUPADO: 'Ocupado',
}


def esta_ocupado(agendamentos, agora=None):
    """True se algum agendamento cobre o instante `agora`.

    `agendamentos` deve ser uma lista/iterável de agendamentos JÁ filtrados
    como não cancelados e com horário de fim no futuro.
    """
    if agora is None:
        agora = timezone.now()

    for agendamento in agendamentos:
        if agendamento.horario_inicio <= agora <= agendamento.horario_fim:
            return True
    return False


def calcular_status(computador, agendamentos, agora=None):
    """Retorna 'D', 'M' ou 'O' para o computador, sem gravar no banco."""
    if computador.status == STATUS_MANUTENCAO:
        # Manutenção sempre vence: nada é agendado numa máquina quebrada.
        return STATUS_MANUTENCAO

    if esta_ocupado(agendamentos, agora):
        return STATUS_OCUPADO

    return STATUS_DISPONIVEL


def rotulo_status(status):
    return ROTULOS.get(status, ROTULOS[STATUS_DISPONIVEL])
