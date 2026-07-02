from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.contrib.auth import authenticate 
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

# Formulário customizado com interceptação total de mensagens
class CustomAuthForm(AuthenticationForm):
    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if username and password:
            # Autentica usando a função nativa do Django
            self.user_cache = authenticate(
                self.request, 
                username=username, 
                password=password
            )
            
            # Se os dados estiverem errados ou usuário não existir
            if self.user_cache is None:
                raise ValidationError(
                    "Usuário ou senha incorretos.",
                    code='invalid_login',
                )
            # Se os dados estiverem certos, mas a conta for inativa (is_active=False)
            elif not self.user_cache.is_active:
                raise ValidationError(
                    "Login inválido. Se você já se cadastrou, aguarde o administrador autorizar o seu acesso.",
                    code='inactive',
                )
                
        return self.cleaned_data

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # 1. Rota de login principal forçando nosso formulário
    path('', auth_views.LoginView.as_view(
        template_name='registration/login.html', 
        authentication_form=CustomAuthForm
    ), name='login'),

    # 2. Rota alternativa caso o Django redirecione para o padrão /accounts/login/
    path('accounts/login/', auth_views.LoginView.as_view(
        template_name='registration/login.html', 
        authentication_form=CustomAuthForm
    )),

    path('agendamento/', include('Mapeamento.urls')),  
    path('accounts/', include('django.contrib.auth.urls')),
]