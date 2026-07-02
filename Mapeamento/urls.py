from django.urls import path
from . import views

app_name = 'mapeamento'

urlpatterns = [
    # Mapeia diretamente o painel principal em /agendamento/
    path('', views.lista_computadores, name='home'),
    
    # Mapeia a ação de envio em /agendamento/agendar/
    path('agendar/', views.agendar_computador, name='agendar'), 
    
    # Mapeia a API de horários em /agendamento/horarios_disponiveis/
    path('horarios_disponiveis/', views.get_horarios_disponiveis, name='horarios_disponiveis'),

    
]