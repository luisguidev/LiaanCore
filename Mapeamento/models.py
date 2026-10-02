from django.db import models
from django.db.models import F, Q
from django.contrib.auth.models import User
from django.utils import timezone


class Computador(models.Model):
    nome = models.CharField(max_length=30, unique=True, verbose_name="Nome do Computador")
    ip_lm_studio = models.GenericIPAddressField(null=True, blank=True, verbose_name="LM-Studio")
    placa_de_video = models.CharField(max_length=150, verbose_name="Placa de Vídeo")
    id_anydesk = models.CharField(max_length=50, null=True, blank=True, verbose_name="AnyDesk")

    # 'status' guarda APENAS o estado manual do equipamento.
    # 'Ocupado' NÃO é salvo no banco: é sempre calculado a partir dos
    # agendamentos em andamento (ver Mapeamento/status.py).
    DISPONIBILIDADE_CHOICES = (
        ('D', 'Disponível'),
        ('M', 'Manutenção'),
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


class AgendamentoManager(models.Manager):
    """Manager com um atalho para os agendamentos que ainda valem.

    Um agendamento cancelado (soft delete) continua no banco por histórico,
    mas não deve aparecer no painel nem bloquear um novo horário.
    """

    def ativos(self):
        return self.filter(cancelado=False)


class Agendamento(models.Model):
    computador = models.ForeignKey(
        Computador,
        on_delete=models.PROTECT,
        related_name='agendamentos',
        verbose_name="Computador Agendado"
    )
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='agendamentos',
        verbose_name="Usuário"
    )
    horario_inicio = models.DateTimeField(verbose_name="Horário de Início")
    horario_fim = models.DateTimeField(verbose_name="Horário Final")
    data_criacao = models.DateTimeField(auto_now_add=True, verbose_name="Data de Criação")
    data_atualizacao = models.DateTimeField(auto_now=True, verbose_name="Última Alteração")

    # --- Soft delete: o registro é preservado para auditoria ---
    cancelado = models.BooleanField(default=False, verbose_name="Cancelado")
    data_cancelamento = models.DateTimeField(
        null=True, blank=True, verbose_name="Data do Cancelamento"
    )
    cancelado_por = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='agendamentos_cancelados',
        verbose_name="Cancelado por"
    )

    objects = AgendamentoManager()

    class Meta:
        verbose_name = "Agendamento"
        verbose_name_plural = "Agendamentos"
        ordering = ['horario_inicio', 'horario_fim']
        indexes = [
            models.Index(fields=['computador', 'horario_inicio']),
            models.Index(fields=['cancelado']),
        ]
        constraints = [
            # Última linha de defesa: o banco recusa horário final <= inicial.
            models.CheckConstraint(
                # Só as reservas ATIVAS precisam ter fim depois do início.
                # Cancelados são histórico e preservamos os horários originais,
                # mesmo que venham de um período em que a validação não rodava.
                condition=Q(horario_fim__gt=F('horario_inicio')) | Q(cancelado=True),
                name='agendamento_fim_depois_do_inicio',
            ),
        ]

    def __str__(self):
        prefixo = '[CANCELADO] ' if self.cancelado else ''
        return (
            f"{prefixo}Agendamento de {self.usuario.username} em {self.computador.nome} "
            f"({timezone.localtime(self.horario_inicio).strftime('%d/%m %H:%M')})"
        )

    # --- Regra de permissão de exclusão ---
    # Fonte única da verdade: usada pela view, pela template tag e pelo JSON
    # do polling, garantindo que nunca divirjam entre si.
    def pode_excluir(self, user):
        """Apenas administradores ou o dono do agendamento podem excluir."""
        if not user.is_authenticated:
            return False
        return user.is_superuser or user.is_staff or self.usuario_id == user.pk

    def marcar_cancelado(self, user):
        """Aplica o soft delete preservando quem cancelou e quando."""
        self.cancelado = True
        self.data_cancelamento = timezone.now()
        self.cancelado_por = user if user.is_authenticated else None
        self.save(update_fields=['cancelado', 'data_cancelamento', 'cancelado_por', 'data_atualizacao'])


class TentativaRateLimit(models.Model):
    """Contador de tentativas para o rate limiting de login e cadastro.

    Fica no Postgres, e não no cache, por dois motivos:

    1. O cache LocMem é POR PROCESSO. Com mais de um worker do Gunicorn cada um
       teria o seu próprio contador, e o limite seria burlado caindo em workers
       diferentes — além de tudo zerar a cada deploy.
    2. Um cache exigiria Redis (mais uma peça de infraestrutura) só para guardar
       um número. Aqui o Postgres já está no lugar.

    Uma linha por (chave, janela). A janela é FIXA, alinhada em blocos de
    `janela_segundos`, e não deslizante: é mais barata e a semântica é a mesma
    que existia quando o contador vivia no cache.
    """

    chave = models.CharField(max_length=100, verbose_name="Chave")
    janela_inicio = models.DateTimeField(verbose_name="Início da Janela")
    contagem = models.PositiveIntegerField(default=0, verbose_name="Contagem")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Tentativa de Rate Limit"
        verbose_name_plural = "Tentativas de Rate Limit"
        ordering = ['-janela_inicio']
        constraints = [
            # Uma linha por chave e janela. É esta constraint que faz o
            # get_or_create resolver a corrida de inserção entre workers.
            models.UniqueConstraint(
                fields=['chave', 'janela_inicio'],
                name='tentativa_chave_janela_unica',
            ),
        ]
        indexes = [
            # Usada pela varredura que apaga janelas antigas.
            models.Index(fields=['janela_inicio'], name='Mapeamento__janela__idx'),
        ]

    def __str__(self):
        return f'{self.chave} @ {timezone.localtime(self.janela_inicio):%d/%m %H:%M} = {self.contagem}'
