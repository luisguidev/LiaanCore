# Mapeamento/urls.py

from django.urls import path
from . import views

# O 'app_name' é importante para referenciar as URLs em templates (ex: {% url 'mapeamento:home' %})
app_name = 'mapeamento'

urlpatterns = [
    # Mapeia a página inicial
    path('', views.lista_computadores, name='home'),
    
    # Mapeia a URL que o formulário está chamando
    path('agendar/', views.agendar_computador, name='agendar'), 
    path('horarios_disponiveis/', views.get_horarios_disponiveis, name='horarios_disponiveis'),
]