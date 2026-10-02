# Fases de deploy no Render.
#
# Sem isso o build só instalava as dependências: o collectstatic nunca rodava
# e, com DEBUG=0, o storage usa CompressedManifestStaticFilesStorage, que dá
# erro em qualquer {% static %} sem o manifest — ou seja, TODAS as páginas
# respondiam 500. E a migração 0003 (tabela do rate limit) nunca era criada.
#
# `release` roda depois do build e antes do novo deploy receber tráfego, o que
# torna seguro aplicar migração e coletar estáticos ali.
release: python manage.py collectstatic --noinput && python manage.py migrate --noinput

# 2 workers x 4 threads = 8 requisições simultâneas. Mantido baixo de propósito:
# o pool do Supabase é limitado e cada conexão aberta conta contra ele.
# Ajuste CONN_MAX_AGE em settings.py se o uso crescer.
web: gunicorn liaancore.wsgi:application --workers 2 --threads 4 --timeout 120