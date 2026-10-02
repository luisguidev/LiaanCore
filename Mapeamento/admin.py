from django.contrib import admin
from django.contrib import messages
from django.conf import settings
from django.template.response import TemplateResponse
from django.urls import reverse
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.utils.translation import gettext as _

from django.utils.html import format_html

from .models import Computador, Agendamento
from .ratelimit import client_ip, excedeu_limite


class MapeamentoAdminSite(admin.AdminSite):
    """Admin do Django com rate limit no login.

    Sem isto o painel fica com um furo: o `CustomAuthForm` (que tem rate limit)
    só está em `/accounts/login/`. O `/admin/login/` usa o
    `AdminAuthenticationForm` do próprio Django, que NÃO tem limite nenhum — e
    quem controla o superuser controla o laboratório inteiro.

    O limite é aplicado por IP antes de qualquer checagem de credencial, então
    vale tanto para senha errada quanto para tentativa válida e repetida.
    """

    def login(self, request, extra_context=None):
        if request.method == 'POST':
            janela, maximo = settings.RATE_LIMIT_LOGIN_ADMIN
            if excedeu_limite(f'admin:{client_ip(request)}', janela, maximo):
                messages.error(
                    request,
                    'Muitas tentativas de acesso ao painel administrativo. '
                    'Aguarde alguns minutos e tente novamente.',
                )
                return self._tela_de_login_bloqueada(request, extra_context)

        return super().login(request, extra_context)

    def _tela_de_login_bloqueada(self, request, extra_context=None):
        """Reexibe o formulário de login com 429 em vez de processar o POST.

        Reproduz o contexto que `AdminSite.login()` monta, para o template
        `admin/login.html` renderizar igual. O formulário é montado com os
        dados do POST sem ser validado, então nenhum erro de credencial é
        devolvido — só a mensagem de bloqueio.
        """
        # Import dentro do método: `django.contrib.admin.forms` importa o model
        # de User, e o módulo admin não pode fazer isso na importação do app.
        from django.contrib.admin.forms import AdminAuthenticationForm

        request.current_app = self.name

        contexto = {
            **self.each_context(request),
            'title': _('Log in'),
            'subtitle': None,
            'app_path': request.get_full_path(),
            'username': request.POST.get('username', ''),
            'form': AdminAuthenticationForm(request, data=request.POST),
            REDIRECT_FIELD_NAME: reverse('admin:index', current_app=self.name),
        }
        contexto.update(extra_context or {})

        return TemplateResponse(
            request,
            self.login_template or 'admin/login.html',
            contexto,
            status=429,
        )


@admin.register(Computador)
class ComputadorAdmin(admin.ModelAdmin):
    list_display = ('nome', 'placa_de_video', 'status', 'ip_lm_studio')

    list_filter = ('status', 'placa_de_video')

    search_fields = ('nome', 'placa_de_video', 'id_anydesk')

    # 'Ocupado' não é gravado: o status é calculado a partir dos agendamentos.
    list_editable = ('status',)


@admin.register(Agendamento)
class AgendamentoAdmin(admin.ModelAdmin):
    list_display = ('computador', 'usuario', 'horario_inicio', 'horario_fim', 'situacao', 'data_criacao')
    list_filter = ('computador', 'usuario', 'cancelado')
    search_fields = ('usuario__username', 'computador__nome')
    readonly_fields = ('data_criacao', 'data_atualizacao', 'data_cancelamento', 'cancelado_por')
    list_select_related = ('computador', 'usuario', 'cancelado_por')

    fieldsets = (
        (None, {
            'fields': ('computador', 'usuario', 'horario_inicio', 'horario_fim', 'cancelado')
        }),
        ('Auditoria', {
            'fields': ('data_criacao', 'data_atualizacao', 'data_cancelamento', 'cancelado_por')
        }),
    )

    @admin.display(description='Situação', ordering='cancelado')
    def situacao(self, obj):
        if obj.cancelado:
            quem = obj.cancelado_por.username if obj.cancelado_por else '—'
            return format_html('<b>Cancelado</b> por {}', quem)
        return format_html('Ativo')