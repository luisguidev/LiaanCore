"""Rate limiting simples baseado no Postgres.

Protege o cadastro e o login contra abuso/brute-force.

Por que o Postgres e não o cache: o cache LocMem do Django é POR PROCESSO.
Com mais de um worker do Gunicorn cada um teria seu próprio contador, então o
limite seria burlado caindo em workers diferentes — e tudo zeraria a cada
deploy. Um cache compartilhado exigiria Redis, que é mais uma peça de
infraestrutura só para guardar um contador. O Postgres já está no lugar.

A contagem é feita com um UPDATE atômico (`contagem = contagem + 1`) em vez do
padrão ler -> decidir -> gravar, que perde incrementos quando duas requisições
chegam juntas.
"""

import random
from datetime import datetime, timezone as dt_timezone

from django.db.models import F
from django.utils import timezone

from .models import TentativaRateLimit

# Uma em cada N chamadas dispara a limpeza das janelas vencidas. Precisa ser
# improvável o bastante para não custar nada, mas frequente o bastante para que a
# tabela não cresça sem parar.
CHANCE_DE_LIMPEZA = 50

# Janelas mais velhas que isto saem na limpeza automática.
IDADE_MAXIMA_JANELAS = 86400  # 24 horas


def client_ip(request):
    """IP do cliente, respeitando o proxy do Render."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def inicio_da_janela(janela_segundos, momento=None):
    """Alinha a janela em blocos de `janela_segundos`.

    Sem isso cada requisição cairia numa janela diferente e criaria uma linha
    nova — o contador nunca se acumularia. A partir daqui, todas as tentativas
    dentro do mesmo bloco compartilham a mesma linha.
    """
    momento = momento or timezone.now()
    bloco = int(momento.timestamp() // janela_segundos) * janela_segundos
    return datetime.fromtimestamp(bloco, tz=dt_timezone.utc)


def _limpar_janelas_vencidas(chave, janela_segundos):
    """Apaga as janelas antigas DESTA chave. Barato: só toca na própria chave."""
    TentativaRateLimit.objects.filter(
        chave=chave,
        janela_inicio__lt=inicio_da_janela(janela_segundos)
        - timezone.timedelta(seconds=IDADE_MAXIMA_JANELAS),
    ).delete()


def excedeu_limite(chave, janela_segundos, maximo):
    """Conta uma tentativa e diz se o limite foi atingido.

    Retorna True quando a tentativa deve ser BLOQUEADA.
    """
    if random.randint(1, CHANCE_DE_LIMPEZA) == 1:
        _limpar_janelas_vencidas(chave, janela_segundos)

    inicio = inicio_da_janela(janela_segundos)

    # get_or_create + UniqueConstraint: se dois workers chegarem juntos na
    # primeira tentativa, só um insere e o outro reaproveita a linha.
    registro, _criado = TentativaRateLimit.objects.get_or_create(
        chave=chave,
        janela_inicio=inicio,
        defaults={'contagem': 0},
    )

    # Incremento atômico: um único UPDATE. Duas requisições simultâneas não
    # perdem contagem, porque cada UPDATE soma 1 sobre o valor corrente no banco.
    TentativaRateLimit.objects.filter(pk=registro.pk).update(
        contagem=F('contagem') + 1
    )
    registro.refresh_from_db(fields=['contagem'])

    # `maximo` tentativas passam; a seguinte é bloqueada.
    return registro.contagem > maximo


def limpar_tudo():
    """Zera todos os contadores. Usado nos testes."""
    TentativaRateLimit.objects.all().delete()