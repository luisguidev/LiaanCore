# Mapeamento/urls.py

from django.urls import path
from . import views

# O 'app_name' é importante para referenciar as URLs em templates (ex: {% url 'mapeamento:home' %})
app_name = 'Mapeamento'

urlpatterns = [
    # O path('', ...) define que esta view será a página inicial/raiz do app Mapeamento.
    # O name='home' permite que você chame esta URL por um nome, não apenas pelo path.
    path('', views.lista_computadores, name='home'),
]