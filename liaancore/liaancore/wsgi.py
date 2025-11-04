"""
WSGI config for liaancore project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
from django.core.wsgi import get_wsgi_application

# --- ADICIONE ESTE BLOCO PARA MIGRAR NO PRIMEIRO BUILD ---
if os.environ.get('DJANGO_MIGRATE', None) == '1':
    from django.core.management import call_command
    print("Executando migrações no banco de dados...")
    call_command('migrate', interactive=False)
    print("Migrações concluídas.")
# --------------------------------------------------------

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'liaancore.settings')
application = get_wsgi_application()
