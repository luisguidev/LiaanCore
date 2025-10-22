# Create your views here.
from django.shortcuts import render
from .models import Computador

# View para listar todos os computadores
def lista_computadores(request):
    # Pega todos os objetos da classe Computador no banco de dados
    # O .all() retorna um QuerySet (lista) com todos os PCs
    computadores = Computador.objects.all()
    
    # Renderiza o template 'mapeamento/lista_computadores.html' 
    # e passa a lista de computadores para o template através do dicionário 'context'.
    context = {
        'computadores': computadores
    }
    return render(request, 'mapeamento/main.html', context)