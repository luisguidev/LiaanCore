# liaancore/wsgi.py (Versão Temporária Simplificada)

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'liaancore.settings')
application = get_wsgi_application()