# liaancore/wsgi.py

import os
from django.core.wsgi import get_wsgi_application
from django.conf import settings 

# --- IMPORTANTE: BLOCO DE CÓDIGO TEMPORÁRIO PARA MIGRAR O BANCO DE DADOS ---

# Verifica se estamos em um ambiente de build e se a migração deve ser forçada
# (Você define esta variável na Vercel ou no vercel.json)
if os.environ.get('APPLY_MIGRATIONS', None) == '1':
    try:
        # Define as configurações para garantir que os comandos funcionem
        # Isso é necessário porque call_command exige que o ambiente esteja configurado.
        if not settings.configured:
            os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'liaancore.settings')
            
        from django.core.management import call_command
        print("Executando migrações no banco de dados Render...")
        call_command('migrate', interactive=False)
        print("Migrações concluídas com sucesso!")
        
    except Exception as e:
        print(f"Erro durante a migração: {e}")
        # É importante que o erro não trave o build, mas queremos registrá-lo

# --------------------------------------------------------------------------

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'liaancore.settings')
application = get_wsgi_application()