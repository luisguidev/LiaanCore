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

# Headers que a borda do Render (Cloudflare) DEFINE com o IP real do cliente.
#
# A diferença para o X-Forwarded-For é que estes são sobrescritos pela borda: o
# cliente mandar o header não muda nada. O XFF é apenas anexado, então o
# primeiro valor é escolhido pelo cliente e um `X-Forwarded-For: 1.2.3.4`
# numa requisição por vez zera o contador do rate limit.
#
# Por isso estes dois vem PRIMEIRO. Se a borda não os enviar, caímos no XFF
# (comportamento anterior, preservado de propósito: o formato exato do XFF no
# Render não é documentado, e trocar a posição com base em suposição poderia
# fazer todo mundo cair no mesmo bucket do IP da borda e bloquear o
# laboratório inteiro).
HEADERS_DE_IP_CONFIAVEL = (
    'HTTP_TRUE_CLIENT_IP',      # Cloudflare
    'HTTP_CF_CONNECTING_IP',    # Cloudflare
)


def client_ip(request):
    """IP do cliente para uso no rate limiting.

    ATENÇÃO: este valor é um sinal de APOIO, nunca a única defesa. A borda do
    Render é a única fonte confiável de IP, e nada aqui garante o formato do
    header que ela envia. Por isso o limite por usuário (ver
    `chave_login`) existe: ele não depende de nenhum header.
    """
    for header in HEADERS_DE_IP_CONFIAVEL:
        valor = request.META.get(header, '').strip()
        if valor:
            return valor

    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def chave_login(usuario):
    """Chave de rate limit por CONTA, independente de IP.

    O limite por IP não fecha a força bruta: quem não sabe de qual rede o
    alvo vem (VPN, botnet) gira o IP a cada tentativa e cada uma cai numa
    janela nova. Este contador é por nome de usuário, então o atacante precisa
    errar a senha muitas vezes contra a MESMA conta para travar — que é
    exatamente o ataque que queremos interromper.

    O limite é propositalmente bem mais alto que o de IP, para que uma pessoa
    não tranque a própria conta de fora: bloquear conta é DoS, e o atacante
    poderia usar isso para deixar o alvo sem acesso. Por isso a janela é curta
    e o teto generoso — o custo de um bloqueio é menor que o de uma senha
    adivinhada.
    """
    return f'login-user:{usuario.strip().lower()}'


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