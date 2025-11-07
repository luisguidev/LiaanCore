from django.contrib import admin
from .models import Computador, Agendamento # Importamos as classes que queremos registrar

# 1. Configuração para o Modelo Computador
@admin.register(Computador)
class ComputadorAdmin(admin.ModelAdmin):
    # Define quais campos aparecerão na lista principal do Admin
    list_display = ('nome', 'placa_de_video', 'status', 'ip_lm_studio')
    
    # Adiciona filtros laterais
    list_filter = ('status', 'placa_de_video')
    
    # Adiciona uma caixa de pesquisa
    search_fields = ('nome', 'placa_de_video', 'id_anydesk')
    
    # Permite alterar o status diretamente na lista
    list_editable = ('status',) 

# 2. Configuração para o Modelo Agendamento
@admin.register(Agendamento)
class AgendamentoAdmin(admin.ModelAdmin):
    list_display = ('computador', 'usuario', 'horario_inicio', 'horario_fim', 'data_criacao')
    list_filter = ('computador', 'usuario')
    search_fields = ('usuario__username', 'computador__nome')
    # Organiza a exibição dos campos na página de edição
    fieldsets = (
        (None, {
            'fields': ('computador', 'usuario', 'horario_inicio', 'horario_fim')
        }),
    )