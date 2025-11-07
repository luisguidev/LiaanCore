# liaancore/wsgi.py (Versão FINAL para Serverless Function)

import os
from django.core.wsgi import get_wsgi_application

# Removemos o bloco 'if os.environ.get('APPLY_MIGRATIONS', None) == '1': ...'

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'liaancore.settings')
application = get_wsgi_application()