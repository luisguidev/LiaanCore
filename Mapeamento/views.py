from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Max
from django.http import (
    HttpResponseForbidden,
    HttpResponseNotModified,
    JsonResponse,
)
from django.views.decorators.http import require_POST

from .models import Agendamento, Computador
from .forms import AgendamentoForm
from .ratelimit import client_ip, excedeu_limite
from .status import (
    STATUS_MANUTENCAO,
    calcular_status,
    rotulo_status,
)

from django.utils import timezone
from datetime import datetime, timedelta

from django.contrib.auth.forms import UserCreationForm
from django.conf import settings

import resend

# Intervalo entre os pontos de tempo oferecidos no formulário (30 minutos).
INTERVALO_MINUTOS = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agendamentos_visiveis_agora():
    """Agendamentos não cancelados que ainda estão valendo (em curso ou futuros)."""
    return (
        Agendamento.objects.ativos()
        .filter(horario_fim__gte=timezone.now())
        .select_related('usuario', 'computador')
        .order_by('horario_inicio')
    )


def _agrupar_por_computador(agendamentos):
    """{id_computador: [agendamento, ...]} preservando a ordenação por início."""
    agrupados = {}
    for agendamento in agendamentos:
        agrupados.setdefault(agendamento.computador_id, []).append(agendamento)
    return agrupados


def _serializar_computadores(agendamentos_por_pc, request):
    """Estrutura usada tanto no template quanto no JSON de tempo real.

    O status enviado é sempre o EFETIVO (calculado), nunca o valor cru do banco.
    """
    agora = timezone.now()
    computadores = Computador.objects.all()
    cards = []

    for computador in computadores:
        agendamentos = agendamentos_por_pc.get(computador.id, [])
        status = calcular_status(computador, agendamentos, agora)
        cards.append({
            'id': computador.id,
            'nome': computador.nome,
            'gpu': computador.placa_de_video,
            'ip': computador.ip_lm_studio,
            'anydesk': computador.id_anydesk,
            'status': status,
            'rotulo': rotulo_status(status),
            'em_manutencao': computador.status == STATUS_MANUTENCAO,
            'agendamentos': [
                {
                    'id': a.id,
                    'usuario': a.usuario.username,
                    'inicio': timezone.localtime(a.horario_inicio).strftime('%d/%m %H:%M'),
                    'fim': timezone.localtime(a.horario_fim).strftime('%d/%m %H:%M'),
                    'pode_excluir': a.pode_excluir(request.user),
                    'inicio_iso': timezone.localtime(a.horario_inicio).strftime('%Y-%m-%dT%H:%M'),
                    'fim_iso': timezone.localtime(a.horario_fim).strftime('%Y-%m-%dT%H:%M'),
                }
                for a in agendamentos
            ],
        })

    return cards


def _versao_atual():
    """Assinatura barata do estado dos agendamentos, usada como ETag.

    Qualquer criação, edição ou cancelamento altera (total, maior id ou última
    alteração), então o 304 do navegador nunca mente sobre dado novo.
    """
    agregado = Agendamento.objects.ativos().aggregate(
        total=Count('id'),
        maior_id=Max('id'),
        ultima=Max('data_atualizacao'),
    )
    ultima = agregado['ultima']
    return (
        f"v{agregado['total']}-"
        f"{agregado['maior_id'] or 0}-"
        f"{int(ultima.timestamp()) if ultima else 0}"
    )


def _montar_etag(versao, user):
    return f'W/"{versao}-u{user.pk}"'


def _montar_contexto(request, agendamento_form=None, modal_aberto=False, pc_id=None):
    """Contexto compartilhado entre a página inicial e o re-render após erro."""
    agendamentos_por_pc = _agrupar_por_computador(_agendamentos_visiveis_agora())
    cards = _serializar_computadores(agendamentos_por_pc, request)
    versao = _versao_atual()

    return {
        'cards': cards,
        'agendamentos_por_pc': agendamentos_por_pc,
        'form': agendamento_form if agendamento_form is not None else AgendamentoForm(),
        'versao': versao,
        'etag': _montar_etag(versao, request.user),
        'modal_aberto': modal_aberto,
        'pc_id': pc_id,
    }


# ---------------------------------------------------------------------------
# Views principais
# ---------------------------------------------------------------------------

@login_required
def lista_computadores(request):
    return render(request, 'mapeamento/main.html', _montar_contexto(request))


@login_required
def agendar_computador(request):
    """Cria o agendamento.

    Toda a validação vive no AgendamentoForm (inclusive o lock transacional).
    Em caso de erro a página é re-renderizada com o modal aberto e já
    preenchido, em vez de redirecionar e perder o que o usuário digitou.
    """
    if request.method != 'POST':
        return redirect('mapeamento:home')

    form = AgendamentoForm(request.POST)
    pc_id = request.POST.get('computador')

    if form.is_valid():
        agendamento = form.save(usuario=request.user)
        messages.success(
            request,
            f"Agendamento do {agendamento.computador.nome} realizado com sucesso!"
        )
        return redirect('mapeamento:home')

    for erro in form.non_field_errors():
        messages.error(request, erro)

    return render(
        request,
        'mapeamento/main.html',
        _montar_contexto(request, agendamento_form=form, modal_aberto=True, pc_id=pc_id),
    )


@login_required
@require_POST
def excluir_agendamento(request, pk):
    """Exclui (soft delete) um agendamento.

    Regra: apenas administradores (staff/superuser) ou o dono do agendamento
    podem excluir. A checagem é explícita e devolve 403 — não 404 — para não
    esconder que o registro existe.
    """
    agendamento = get_object_or_404(Agendamento, pk=pk)

    if not agendamento.pode_excluir(request.user):
        return HttpResponseForbidden(
            "Você não tem permissão para excluir este agendamento."
        )

    ja_cancelado = agendamento.cancelado

    if not ja_cancelado:
        agendamento.marcar_cancelado(request.user)

    mensagem = (
        "Este agendamento já estava cancelado."
        if ja_cancelado
        else "Agendamento excluído com sucesso."
    )

    # Resposta JSON quando chamado pelo polling, redirect quando é POST normal.
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'ok': True,
            'mensagem': mensagem,
            'versao': _versao_atual(),
        })

    messages.success(request, mensagem)
    return redirect('mapeamento:home')


@login_required
def get_horarios_disponiveis(request):
    """Pontos de tempo de 30 em 30 minutos, apenas os LIVRES para o PC.

    Recebe `data` e `computador_id`. Opcionalmente `inicio` (YYYY-MM-DDTHH:MM)
    para já devolver somente os pontos posteriores ao horário de início escolhido.
    """
    data_str = request.GET.get('data')
    computador_id = request.GET.get('computador_id')

    if not data_str or not computador_id:
        return JsonResponse({'error': 'Data ou computador ausente.'}, status=400)

    try:
        data_selecionada = datetime.strptime(data_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Data inválida.'}, status=400)

    try:
        computador = Computador.objects.get(pk=computador_id)
    except (Computador.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'error': 'Computador inválido.'}, status=400)

    inicio_str = request.GET.get('inicio')
    inicio_minimo = None
    if inicio_str:
        try:
            inicio_minimo = timezone.make_aware(
                datetime.strptime(inicio_str, '%Y-%m-%dT%H:%M')
            )
        except ValueError:
            return JsonResponse({'error': 'Horário de início inválido.'}, status=400)

    # Dia local do usuário: 00:00 -> 24:00 (exclusive).
    inicio_do_dia = timezone.make_aware(datetime.combine(data_selecionada, datetime.min.time()))
    fim_do_dia = inicio_do_dia + timedelta(days=1)
    agora = timezone.now()

    # Horários já ocupados por este computador.
    ocupados = Agendamento.objects.ativos().filter(
        computador=computador,
        horario_fim__gt=agora,
        horario_inicio__lt=fim_do_dia,
    ).values_list('horario_inicio', 'horario_fim')

    agendamentos_do_dia = list(ocupados)

    def conflita_com_algum(momento):
        """True se começar neste ponto sobreporia algum agendamento existente.

        O candidato é tratado como um INTERVALO [momento, momento+30min], e
        não como um instante. Testar só o instante faria o início exato de um
        agendamento (ex.: reserva das 15:00) parecer "livre".
        """
        fim_do_ponto = momento + timedelta(minutes=INTERVALO_MINUTOS)
        return any(
            inicio < fim_do_ponto and fim > momento
            for inicio, fim in agendamentos_do_dia
        )

    pontos = []
    momento = inicio_do_dia
    # `while <` (e não `<=`) evita oferecer as 00:00 do dia seguinte, o que
    # permitiria atravessar a meia-noite.
    while momento < fim_do_dia:
        if momento >= agora and (inicio_minimo is None or momento > inicio_minimo):
            if not conflita_com_algum(momento):
                pontos.append({
                    'display': momento.strftime('%H:%M'),
                    'value': momento.strftime('%Y-%m-%dT%H:%M'),
                })
        momento += timedelta(minutes=INTERVALO_MINUTOS)

    return JsonResponse({
        'pontos': pontos,
        'data': data_selecionada.strftime('%Y-%m-%d'),
    })


@login_required
def estado_json(request):
    """Endpoint de tempo real: estado do laboratório para polling com ETag.

    Responde 304 (sem corpo) quando nada mudou desde a última leitura, e 200
    com o snapshot completo caso contrário.
    """
    # O ETag é "salted" com o usuário porque `pode_excluir` depende de quem
    # está logado: sem isso um 304 poderia reaproveitar dados de permissões
    # de outro usuário.
    versao = _versao_atual()
    etag = _montar_etag(versao, request.user)

    if request.headers.get('If-None-Match') == etag:
        return HttpResponseNotModified(headers={'ETag': etag})

    agendamentos_por_pc = _agrupar_por_computador(_agendamentos_visiveis_agora())

    payload = {
        'versao': versao,
        'computadores': _serializar_computadores(agendamentos_por_pc, request),
    }

    resposta = JsonResponse(payload)
    resposta['ETag'] = etag
    resposta['Cache-Control'] = 'no-cache, private'
    return resposta


# ---------------------------------------------------------------------------
# Cadastro
# ---------------------------------------------------------------------------

def signup_view(request):
    """Cadastro de usuários com aprovação manual do administrador."""
    if request.method == "POST":
        janela, maximo = settings.RATE_LIMIT_CADASTRO
        if excedeu_limite(f'cadastro:{client_ip(request)}', janela, maximo):
            messages.error(
                request,
                "Muitas tentativas de cadastro a partir deste dispositivo. "
                "Tente novamente mais tarde."
            )
            return render(
                request,
                'registration/signup.html',
                {'form': UserCreationForm(request.POST)},
            )

        form = UserCreationForm(request.POST)

        if form.is_valid():
            # 1. Salva o usuário inativo no banco (aguarda aprovação do admin).
            user = form.save(commit=False)
            user.is_active = False
            user.save()

            # 2. Avisa o administrador via Resend (falha de e-mail não trava o cadastro).
            resend.api_key = settings.RESEND_API_KEY
            html_content = f"""
                <h3>Solicitação de Acesso Pendente</h3>
                <p>O usuário <strong>{user.username}</strong> acabou de se cadastrar no sistema.</p>
                <p>Acesse o painel de administração do LiaanCore para revisar e autorizar a conta deste estudante.</p>
            """
            try:
                resend.Emails.send({
                    "from": "LiaanCore <onboarding@resend.dev>",
                    "to": settings.LIAAN_ADMIN_EMAIL,
                    "subject": "LIAANCORE - Novo usuário pendente de aprovação",
                    "html": html_content,
                })
            except Exception as erro:
                print(f"--- ERRO AO ENVIAR VIA RESEND API: {erro} ---")

            messages.success(
                request,
                "Conta solicitada com sucesso! Um administrador revisará seu acesso em breve."
            )
            return redirect('login')
    else:
        form = UserCreationForm()

    return render(request, 'registration/signup.html', {'form': form})
