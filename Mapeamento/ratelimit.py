"""Rate limiting simples baseado no cache do Django.

Protege o cadastro e o login contra abuso/brute-force.

LIMITAÇÃO IMPORTANTE: o cache padrão é LocMem, que NÃO é compartilhado entre
os workers do Gunicorn. Cada worker teria seu próprio contador. Para proteção
efetiva em produção, defina `CACHE_URL` (ex.: `rediss://...`) no ambiente e
instale o pacote `redis` — o backend Redis passa a ser usado automaticamente
(ver liaancore/settings.py).
"""

from django.core.cache import cache


def client_ip(request):
    """IP do cliente, respeitando o proxy do Render."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def excedeu_limite(chave, janela_segundos, maximo):
    """Conta uma tentativa e diz se o limite foi atingido.

    Retorna True quando a tentativa deve ser BLOQUEADA.
    """
    tentativas = cache.get(chave)
    if tentativas is None:
        cache.set(chave, 1, janela_segundos)
        return False

    if tentativas >= maximo:
        return True

    cache.incr(chave)
    return False
