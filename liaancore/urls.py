from django.contrib import admin
from django.urls import path, include 
from django.contrib.auth.views import LoginView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('agendamento/', include('Mapeamento.urls')),  # 👈 Remova o namespace
    path('accounts/', include('django.contrib.auth.urls')),
]