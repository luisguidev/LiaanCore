from django.contrib.admin.apps import AdminConfig


class LiaanCoreAdminConfig(AdminConfig):
    """AdminConfig que troca o AdminSite padrão pelo LiaanCoreAdminSite.

    O `django.contrib.admin.sites.site` é criado de forma preguiçosa a partir
    de `apps.get_app_config("admin").default_site`. apontar esse atributo para a
    nossa subclasse é a forma suportada de trocar o site inteiro do admin — sem
    monkeypatch e sem duplicar o registro dos models.

    O `name` continua sendo "django.contrib.admin" (herdado de SimpleAdminConfig),
    por isso o app_config ainda é encontrado como "admin" e o autodiscover
    registra User/Group normalmente.
    """

    default_site = 'Mapeamento.admin.MapeamentoAdminSite'