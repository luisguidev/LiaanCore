# Mapeamento/forms.py

from django import forms
from .models import Agendamento
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from django.db.models import Q # Necessário para consultas complexas

class AgendamentoForm(forms.ModelForm):
    # FORMATOS DE INPUT do Python para se adequar ao datetime-local do HTML
    # O Django precisa saber como formatar datas que ele insere no campo.
    input_formats = ['%Y-%m-%dT%H:%M'] 

    horario_inicio = forms.DateTimeField(
        # Adicionamos a lista input_formats aqui
        input_formats=input_formats, 
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        label="Início do Agendamento"
    )
    horario_fim = forms.DateTimeField(
        # Adicionamos a lista input_formats aqui
        input_formats=input_formats,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        label="Fim do Agendamento"
    )
    
    class Meta:
        model = Agendamento
        # Excluímos 'usuario' e 'computador' pois a View irá preenchê-los.
        fields = ['horario_inicio', 'horario_fim']

    # Método de validação principal do Formulário
    def clean(self):
        cleaned_data = super().clean()
        horario_inicio = cleaned_data.get("horario_inicio")
        horario_fim = cleaned_data.get("horario_fim")
        computador = self.initial.get("computador") # O PC será passado pela View

        # 1. Validação Simples: Início vs. Fim
        if horario_inicio and horario_fim:
            if horario_inicio >= horario_fim:
                raise ValidationError(
                    "O horário de início deve ser anterior ao horário final."
                )
            
            # 2. Validação: Agendamentos apenas para o futuro
            if horario_inicio < timezone.now() + timedelta(minutes=1):
                 raise ValidationError(
                    "O agendamento deve ser para o futuro."
                )

            # 3. Validação de Conflito de Horário (A Lógica de Negócio Crucial)
            
            # Buscamos por agendamentos existentes no mesmo computador que:
            # - Começam ANTES do novo fim E
            # - Terminam DEPOIS do novo início
            
            conflitos = Agendamento.objects.filter(
                computador=computador,
                # Evita conflitos onde o novo agendamento começa no mesmo instante em que 
                # um anterior termina, ou vice-versa, permitindo agendamentos adjacentes.
                horario_inicio__lt=horario_fim, 
                horario_fim__gt=horario_inicio
            )

            if conflitos.exists():
                raise ValidationError(
                    f"Conflito de horário! O PC já está agendado entre "
                    f"{conflitos.first().horario_inicio.strftime('%H:%M')} e "
                    f"{conflitos.first().horario_fim.strftime('%H:%M')}."
                )
        
        return cleaned_data