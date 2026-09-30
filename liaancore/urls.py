from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.conf import settings

from Mapeamento.ratelimit import client_ip, excedeu_limite
from Mapeamento.views import signup_view  # Importa a sua view de cadastro


class CustomAuthForm(AuthenticationForm):
    """Login com mensagem amigável para contas aguardando aprovação.

    O backend padrão (ModelBackend) já rejeita usuários inativos, então
    `authenticate()` devolve None para eles. A mensagem é propositalmente
    GENÉRICA: um texto específico ("essa conta existe mas está pendente")
    permitiria enumerar usernames válidos.
    """

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if not (username and password):
            # Deixa os campos obrigatórios do próprio Django reclamarem.
            return self.cleaned_data

        self.user_cache = authenticate(
            self.request, username=username, password=password
        )

        if self.user_cache is None:
            # Cobre credenciais erradas E contas inativas (aguardando
            # aprovação). Texto genérico de propósito: uma mensagem
            # específica permitiria enumerar quais usernames existem.
            janela, maximo = settings.RATE_LIMIT_LOGIN
            if excedeu_limite(f'login:{client_ip(self.request)}', janela, maximo):
                raise ValidationError(
                    "Muitas tentativas de login. Aguarde alguns minutos e tente novamente.",
                    code='invalid_login',
                )

            raise ValidationError(
                "Credenciais inválidas ou conta ainda não aprovada pelo administrador.",
                code='invalid_login',
            )

        self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


def raiz_redirect_view(request):
    """Raiz "" decide o destino com base na sessão."""
    if request.user.is_authenticated:
        return redirect('mapeamento:home')
    return redirect('login')


urlpatterns = [
    path('admin/', admin.site.urls),

    path('', raiz_redirect_view, name='raiz_index'),

    path('accounts/login/', auth_views.LoginView.as_view(
        template_name='registration/login.html',
        authentication_form=CustomAuthForm,
    ), name='login'),

    # Django 5 exige POST para logout; a view já redireciona via LOGOUT_REDIRECT_URL.
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),

    path('accounts/signup/', signup_view, name='signup'),

    # O app Mapeamento escuta em /agendamento/
    path('agendamento/', include('Mapeamento.urls')),
]
