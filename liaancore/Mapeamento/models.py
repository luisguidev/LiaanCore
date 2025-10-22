from django.db import models
from django.contrib.auth.models import User

# Modelo para representar cada computador (o "card")
class Computador(models.Model):
    nome = models.CharField(max_length=30, unique=True, verbose_name="Nome do Computador")
    ip_lm_studio = models.GenericIPAddressField(null=True, blank=True, verbose_name="LM-Studio")
    placa_de_video = models.CharField(max_length=150, verbose_name="Placa de Vídeo")
    id_anydesk = models.CharField(max_length=50, null=True, blank=True, verbose_name="AnyDesk")

    DISPONIBILIDADE_CHOICES = (
        ('D', 'Disponível'),
        ('M', 'Manutenção'),
        ('O', 'Ocupado (em Agendamento)'),
    )
    status = models.CharField(
        max_length=1,
        choices=DISPONIBILIDADE_CHOICES,
        default='D',
        verbose_name="Status de Uso"
    )

    class Meta:
        verbose_name = "Computador"
        verbose_name_plural = "Computadores"
        ordering = ['nome']

    def __str__(self):
        return self.nome

# Modelo para registrar os agendamentos
class Agendamento(models.Model):
    computador = models.ForeignKey(
        Computador,
        on_delete=models.CASCADE,
        related_name='agendamentos',
        verbose_name="Computador Agendado"
    )
    # Supondo que o usuário logado será o que faz o agendamento
    usuario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Usuário"
    )
    horario_inicio = models.DateTimeField(verbose_name="Horário de Início")
    horario_fim = models.DateTimeField(verbose_name="Horário Final")
    data_criacao = models.DateTimeField(auto_now_add=True, verbose_name="Data de Criação")

    class Meta:
        verbose_name = "Agendamento"
        verbose_name_plural = "Agendamentos"
        
    def __str__(self):
        return f"Agendamento de {self.usuario.username} em {self.computador.nome} ({self.horario_inicio.strftime('%d/%m %H:%M')})"