from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from .models import Agendamento, Computador


class AgendamentoForm(forms.ModelForm):
    """Formulário único de agendamento.

    Concentra TODAS as regras de negócio do agendamento (antes elas ficavam
    duplicadas entre a view e o form, e a view nem usava o form):

      1. horário final posterior ao inicial;
      2. início no futuro;
      3. computador existente;
      4. ausência de conflito de horário;
      5. criação serializada por computador (sem corrida entre usuários).
    """

    FORMATOS_INPUT = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S']

    horario_inicio = forms.DateTimeField(
        input_formats=FORMATOS_INPUT,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        label="Início do Agendamento"
    )
    horario_fim = forms.DateTimeField(
        input_formats=FORMATOS_INPUT,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        label="Fim do Agendamento"
    )
    computador = forms.ModelChoiceField(
        queryset=Computador.objects.all(),
        widget=forms.HiddenInput,
        error_messages={
            'required': "Selecione um computador da lista.",
            'invalid_choice': "Computador inválido. Selecione um PC da lista.",
        }
    )

    class Meta:
        model = Agendamento
        fields = ['horario_inicio', 'horario_fim']

    def clean(self):
        cleaned_data = super().clean()
        horario_inicio = cleaned_data.get('horario_inicio')
        horario_fim = cleaned_data.get('horario_fim')
        computador = cleaned_data.get('computador')

        if not (horario_inicio and horario_fim and computador):
            return cleaned_data

        # 1. Início precisa ser estritamente antes do fim.
        if horario_inicio >= horario_fim:
            raise ValidationError("O horário de início deve ser anterior ao horário final.")

        # 2. Não é possível agendar no passado (também protege contra POST forjado).
        if horario_inicio < timezone.now() + timedelta(minutes=1):
            raise ValidationError("O agendamento deve ser para o futuro.")

        # 3. Conflito com outro agendamento válido do mesmo computador.
        #    `ativos()` ignora os cancelados, permitindo reusar o horário livre.
        conflitos = Agendamento.objects.ativos().filter(
            computador=computador,
            horario_inicio__lt=horario_fim,
            horario_fim__gt=horario_inicio,
        )

        if conflitos.exists():
            conflito = conflitos.order_by('horario_inicio').first()
            # timezone.localtime: o valor cru do banco é UTC; sem converter
            # a mensagem mostrava o horário 3 horas atrasado.
            inicio_local = timezone.localtime(conflito.horario_inicio)
            fim_local = timezone.localtime(conflito.horario_fim)
            raise ValidationError(
                f"Conflito de horário! O {computador.nome} já está reservado "
                f"entre {inicio_local.strftime('%d/%m %H:%M')} e "
                f"{fim_local.strftime('%d/%m %H:%M')}."
            )

        return cleaned_data

    def save(self, commit=True, usuario=None):
        """Grava o agendamento serializando por computador.

        `select_for_update()` trava a linha do Computador durante a
        transação. Dois usuários confirmando agendamentos simultâneos no
        mesmo PC são executados em fila: o segundo vê o agendamento do
        primeiro e é rejeitado por conflito, em vez de criar uma sobreposição.
        """
        if usuario is None:
            raise ValueError("save() exige o usuário responsável pelo agendamento.")

        computador = self.cleaned_data['computador']

        if not commit:
            instance = super().save(commit=False)
            instance.usuario = usuario
            instance.computador = computador
            return instance

        with transaction.atomic():
            Computador.objects.select_for_update().get(pk=computador.pk)

            # Revalida o conflito DENTRO da transação (o check do clean()
            # sozinho não protege contra a corrida).
            horario_inicio = self.cleaned_data['horario_inicio']
            horario_fim = self.cleaned_data['horario_fim']
            conflito = Agendamento.objects.ativos().filter(
                computador=computador,
                horario_inicio__lt=horario_fim,
                horario_fim__gt=horario_inicio,
            ).exists()

            if conflito:
                raise ValidationError(
                    "Este horário acabou de ser reservado por outra pessoa. "
                    "Escolha outro horário."
                )

            instance = super().save(commit=False)
            instance.usuario = usuario
            instance.computador = computador
            instance.save()

        return instance
