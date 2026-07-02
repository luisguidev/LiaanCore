from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.contrib.auth import authenticate 
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from Mapeamento.views import signup_view # Importa a sua view de cadastro

# Formulário customizado minimalista mantido
class CustomAuthForm(AuthenticationForm):
    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        if username and password:
            self.user_cache = authenticate(self.request, username=username, password=password)
            if self.user_cache is None:
                raise ValidationError("Usuário ou senha incorretos.", code='invalid_login')
            elif not self.user_cache.is_active:
                raise ValidationError("Login inválido. Se você já se cadastrou, aguarde o administrador autorizar o seu acesso.", code='inactive')
        return self.cleaned_data

# Redirecionamento automático e inteligente da raiz ("")
def raiz_redirect_view(request):
    if request.user.is_authenticated:
        return redirect('mapeamento:home')
    return redirect('login')

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Se bater na raiz, decide o destino baseado no login
    path('', raiz_redirect_view, name='raiz_index'),
    
    # Centralização das views de conta sob o prefixo /accounts/
    path('accounts/login/', auth_views.LoginView.as_view(
        template_name='registration/login.html', 
        authentication_form=CustomAuthForm
    ), name='login'),
    
    path('accounts/signup/', signup_view, name='signup'),

    # O app Mapeamento vai escutar estritamente em /agendamento/
    path('agendamento/', include('Mapeamento.urls')),  
]