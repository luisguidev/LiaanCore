from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required # Para garantir que só usuários logados agendem
from django.contrib import messages
from .models import Computador, Agendamento
from .forms import AgendamentoForm

from django.http import JsonResponse
from django.utils import timezone, dateparse
from datetime import datetime, timedelta
from django.utils.formats import localize

from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login

@login_required
def lista_computadores(request):
    
    agora = timezone.now()

    computadores = Computador.objects.all()
    
    # 🎯 CORREÇÃO CRÍTICA: DEFINIÇÃO DA VARIÁVEL agendamentos_futuros
    agendamentos_futuros = Agendamento.objects.filter(
        # Filtra agendamentos cujo horário de fim é MAIOR OU IGUAL ao momento atual
        horario_fim__gte=timezone.now() 
    ).select_related('usuario', 'computador').order_by('horario_inicio')
    
    # Cria a estrutura de dicionário {ID_PC: [Agendamento1, Agendamento2, ...]}
    agendamentos_por_pc = {}
    
    for agendamento in agendamentos_futuros:
        pc_id = agendamento.computador.id
        if pc_id not in agendamentos_por_pc:
            agendamentos_por_pc[pc_id] = []
        agendamentos_por_pc[pc_id].append(agendamento)
    # --- LÓGICA DE ATUALIZAÇÃO DE STATUS EM TEMPO REAL ---

    for computador in computadores:
        # Se o PC já estiver em Manutenção ('M'), respeitamos isso e não mudamos.
        if computador.status == 'M':
            continue
            
        # Verifica se existe algum agendamento acontecendo AGORA para este PC
        # A chave do dicionário é o ID do computador
        agendamentos_deste_pc = agendamentos_por_pc.get(computador.id, [])
        
        for agendamento in agendamentos_deste_pc:
            # Se AGORA está entre o inicio e o fim do agendamento
            if agendamento.horario_inicio <= agora <= agendamento.horario_fim:
                computador.status = 'O' # Define visualmente como 'Ocupado'
                break # Já achamos um agendamento ativo, para de procurar
    # Criamos uma instância vazia do formulário
    agendamento_form = AgendamentoForm() 

    context = {
        'computadores': computadores,
        'agendamentos_por_pc': agendamentos_por_pc, # Variável que o template usa
        'form': agendamento_form 
    }
   
    return render(request, 'mapeamento/main.html', context)

@login_required # Garante que apenas usuários autenticados possam acessar esta view
def agendar_computador(request):
    
    if request.method == 'POST':
        computador_id = request.POST.get('computador_id')
        horario_inicio_str = request.POST.get('horario_inicio')
        horario_fim_str = request.POST.get('horario_fim')
        
        # 🎯 CÓDIGO DE PROTEÇÃO CONTRA ID VAZIO (CORREÇÃO)
        if not computador_id:
            messages.error(request, "Erro: O identificador do computador está ausente. Por favor, selecione um PC e tente novamente.")
            return redirect('mapeamento:home')
        # FIM DA CORREÇÃO
        
        try:
            # 1. Validação de Existência do PC (Agora só executa se o ID não for vazio)
            computador = get_object_or_404(Computador, pk=computador_id)
            
            # 2. Converte as strings de data/hora para objetos datetime (Inicialmente NAIVE)
            horario_inicio_naive = dateparse.parse_datetime(horario_inicio_str)
            horario_fim_naive = dateparse.parse_datetime(horario_fim_str)
            
            # --- A CORREÇÃO CRÍTICA AQUI ---
            # Torna as datas conscientes do Fuso Horário de São Paulo
            horario_inicio = timezone.make_aware(horario_inicio_naive)
            horario_fim = timezone.make_aware(horario_fim_naive)
            # --------------------------------

            # Garante que as datas são válidas
            if not horario_inicio or not horario_fim:
                 raise ValueError("Formato de data/hora inválido.")
            
            # --- VALIDAÇÕES DE NEGÓCIO (3 a 5) ---
            # (O restante do seu código de validação de início vs. fim, futuro e conflito)
            # ...
            
            # 5. Validação de Conflito de Horário
            conflitos = Agendamento.objects.filter(
                computador=computador,
                horario_inicio__lt=horario_fim, 
                horario_fim__gt=horario_inicio
            )

            if conflitos.exists():
                conflito = conflitos.first()
                
                # --- CORREÇÃO AQUI ---
                # Converte do UTC (Banco) para o fuso horário definido no settings (America/Sao_Paulo)
                inicio_local = timezone.localtime(conflito.horario_inicio)
                fim_local = timezone.localtime(conflito.horario_fim)
                
                # Formata para string bonitinha (Dia/Mês Hora:Minuto)
                inicio_fmt = inicio_local.strftime('%d/%m %H:%M')
                fim_fmt = fim_local.strftime('%d/%m %H:%M')
                
                messages.error(request, 
                               f"Conflito de horário! O {computador.nome} já está agendado entre "
                               f"{inicio_fmt} e {fim_fmt}.")
                return redirect('mapeamento:home')

            # --- SE TODAS AS VALIDAÇÕES PASSARAM: SALVAR ---
            
            Agendamento.objects.create(
                usuario=request.user,
                computador=computador,
                horario_inicio=horario_inicio,
                horario_fim=horario_fim
            )
            
            messages.success(request, f'Agendamento do {computador.nome} realizado com sucesso!')
            return redirect('mapeamento:home')

        except Exception as e:
            # Captura erros de formato de data/hora, ou qualquer erro inesperado
            # Usar 'Exception' aqui é seguro para capturar ValueError, etc.
            messages.error(request, f'Erro interno no agendamento. Detalhes: {e}')
            return redirect('mapeamento:home')
            
    # Se a requisição não for POST
    return redirect('mapeamento:home')

@login_required
def get_horarios_disponiveis(request):
    """
    Recebe a data e retorna todos os pontos de tempo possíveis (a cada 30 min) 
    para popular os dropdowns de Início e Fim.
    A lógica de conflito será feita no momento da submissão do formulário.
    """
    data_str = request.GET.get('data')

    if not data_str:
        return JsonResponse({'error': 'Data incompleta.'}, status=400)

    try:
        data_selecionada = datetime.strptime(data_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Data inválida.'}, status=400)

    # Intervalo de tempo: 00:00 até 23:59 (meia-noite do dia seguinte)
    HORARIO_INICIO_DIA = 0    # Começa às 00:00
    HORARIO_FIM_DIA = 24    # Vai até às 24:00 (que é 00:00 do dia seguinte)
    INTERVALO_MINUTOS = 30  # Pontos de tempo a cada 30 minutos
    
    pontos_de_tempo = []
    
    # --- Lógica de Fuso Horário ---
    # Define o ponto inicial como 00:00 do dia selecionado
    hora_inicial_do_dia_naive = datetime.combine(data_selecionada, datetime.min.time()) + timedelta(hours=HORARIO_INICIO_DIA)
    hora_atual = timezone.make_aware(hora_inicial_do_dia_naive)
    
    # Define o ponto final como 00:00 do dia SEGUINTE
    hora_fim_do_dia_naive = datetime.combine(data_selecionada, datetime.min.time()) + timedelta(hours=HORARIO_FIM_DIA)
    hora_fim_do_dia_aware = timezone.make_aware(hora_fim_do_dia_naive)
    # --- Fim da Lógica de Fuso Horário ---

    # Loop para gerar todos os pontos (de 00:00 até 00:00 do dia seguinte)
    while hora_atual <= hora_fim_do_dia_aware:
        
        # Ignora horários passados
        if hora_atual >= timezone.now():
            pontos_de_tempo.append({
                'display': hora_atual.strftime('%H:%M'),
                'value': hora_atual.strftime('%Y-%m-%dT%H:%M'),
            })

        hora_atual += timedelta(minutes=INTERVALO_MINUTOS) # Avança 30 minutos

    return JsonResponse({'pontos': pontos_de_tempo})

def signup_view(request):
    """
    view para lidar com o cadastro dos usuários
    """

    if request.method == "POST":
        form = UserCreationForm(request.POST)


        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('mapeamento:home')
        
    else:
        form = UserCreationForm()

    
    return render(request, 'registration/signup.html', {'form': form})