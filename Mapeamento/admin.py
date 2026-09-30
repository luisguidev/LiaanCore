from django.contrib import admin
from django.utils.html import format_html
from .models import Computador, Agendamento


@admin.register(Computador)
class ComputadorAdmin(admin.ModelAdmin):
    list_display = ('nome', 'placa_de_video', 'status', 'ip_lm_studio')

    list_filter = ('status', 'placa_de_video')

    search_fields = ('nome', 'placa_de_video', 'id_anydesk')

    # 'Ocupado' não é gravado: o status é calculado a partir dos agendamentos.
    list_editable = ('status',)


@admin.register(Agendamento)
class AgendamentoAdmin(admin.ModelAdmin):
    list_display = ('computador', 'usuario', 'horario_inicio', 'horario_fim', 'situacao', 'data_criacao')
    list_filter = ('computador', 'usuario', 'cancelado')
    search_fields = ('usuario__username', 'computador__nome')
    readonly_fields = ('data_criacao', 'data_atualizacao', 'data_cancelamento', 'cancelado_por')
    list_select_related = ('computador', 'usuario', 'cancelado_por')

    fieldsets = (
        (None, {
            'fields': ('computador', 'usuario', 'horario_inicio', 'horario_fim', 'cancelado')
        }),
        ('Auditoria', {
            'fields': ('data_criacao', 'data_atualizacao', 'data_cancelamento', 'cancelado_por')
        }),
    )

    @admin.display(description='Situação', ordering='cancelado')
    def situacao(self, obj):
        if obj.cancelado:
            quem = obj.cancelado_por.username if obj.cancelado_por else '—'
            return format_html('<b>Cancelado</b> por {}', quem)
        return format_html('Ativo')
