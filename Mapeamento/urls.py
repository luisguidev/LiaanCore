from django.urls import path
from . import views

app_name = 'mapeamento'

urlpatterns = [
    # Painel principal em /agendamento/
    path('', views.lista_computadores, name='home'),

    # Criação de agendamento em /agendamento/agendar/
    path('agendar/', views.agendar_computador, name='agendar'),

    # Exclusão (soft delete) em /agendamento/<pk>/excluir/ — somente POST
    path('<int:pk>/excluir/', views.excluir_agendamento, name='excluir'),

    # API de pontos de tempo livres em /agendamento/horarios_disponiveis/
    path('horarios_disponiveis/', views.get_horarios_disponiveis, name='horarios_disponiveis'),

    # API de tempo real (polling + ETag) em /agendamento/estado/
    path('estado/', views.estado_json, name='estado'),
]
