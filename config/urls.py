"""urls.py del proyecto."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView, TemplateView
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from pasteleria.permissions import SoloAdministrador

urlpatterns = [
    path('admin/', admin.site.urls),                                  # Django Admin
    # Documentación de la API: solo Administrador / superusuario (iniciando sesión en el panel o en /admin/)
    path('api/schema/', SpectacularAPIView.as_view(permission_classes=[SoloAdministrador]), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[SoloAdministrador]), name='api-docs'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema', permission_classes=[SoloAdministrador]), name='api-redoc'),
    path('api/', include('pasteleria.urls')),                         # API REST (/api/ = API root)
    path('api-auth/', include('rest_framework.urls')),                # login/logout de la API navegable
    path('', TemplateView.as_view(template_name='index.html'), name='home'),   # frontend
    # Fotos de comprobantes (en producción lo ideal es servir /media/ con nginx)
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    # Cualquier otra dirección escrita a mano (/hola, /pedidos...) vuelve al inicio en vez de dar 404.
    # Se excluyen /api, /admin, /static, /media y /favicon.ico, que siguen devolviendo su 404 real.
    re_path(r'^(?!api/|api-auth/|admin/|static/|media/|favicon\.ico).+$', RedirectView.as_view(url='/')),
]
