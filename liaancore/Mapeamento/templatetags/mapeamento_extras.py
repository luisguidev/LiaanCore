# Mapeamento/templatetags/mapeamento_extras.py
from django import template
register = template.Library()

@register.filter(name='get_item')
def get_item(dictionary, key):
    # A forma mais robusta de acessar a chave
    if isinstance(dictionary, dict):
         # Tentamos retornar a chave do dicionário (como str ou int)
        return dictionary.get(key)
    return None