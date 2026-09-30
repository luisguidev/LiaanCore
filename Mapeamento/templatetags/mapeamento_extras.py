from django import template

register = template.Library()


@register.filter(name='get_item')
def get_item(dictionary, key):
    """Acessa uma chave de dicionário devolvendo None em vez de erro."""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None


@register.simple_tag
def pode_excluir(agendamento, user):
    """Regra de exclusão em um único lugar.

    Delega para Agendamento.pode_excluir, o mesmo método usado pela view e
    pelo JSON de tempo real. Assim o botão nunca aparece para quem não pode
    excluir, e a view continua sendo a autoridade (403).
    """
    return agendamento.pode_excluir(user)
