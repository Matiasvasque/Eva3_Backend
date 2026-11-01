"""urls.py de la app — router DRF + autenticación."""
from django.urls import include, path
from rest_framework.permissions import AllowAny
from rest_framework.routers import APIRootView, DefaultRouter

from . import views


class RaizAPI(APIRootView):
    """API root (/api/): lista los endpoints sin exigir login. Cada endpoint sigue protegido por rol."""
    permission_classes = [AllowAny]


class RouterDulceArte(DefaultRouter):
    APIRootView = RaizAPI


router = RouterDulceArte()
router.register('pedidos', views.PedidoViewSet, basename='pedido')
router.register('insumos', views.InsumoViewSet, basename='insumo')
router.register('bom', views.DetalleBOMViewSet, basename='bom')
router.register('despachos', views.DespachoViewSet, basename='despacho')
router.register('usuarios', views.UsuarioViewSet, basename='usuario')

urlpatterns = [
    path('auth/me/', views.MeView.as_view(), name='auth-me'),
    path('auth/login/', views.LoginView.as_view(), name='auth-login'),
    path('auth/logout/', views.LogoutView.as_view(), name='auth-logout'),
    path('', include(router.urls)),
]
