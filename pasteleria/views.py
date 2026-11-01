"""views.py — ViewSets (CRUD completo) + autenticación por sesión."""
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DetalleBOM, Despacho, EstadoPedido, Insumo, Pedido
from .permissions import (PermisoPorRol, ROL_ADMIN, ROL_COCINERO, ROL_REPARTIDOR, ROL_VENTAS,
                          es_admin, roles_de, tiene_rol)
from .serializers import (CambioEstadoSerializer, ConfirmarEntregaSerializer, DespachoSerializer,
                          DetalleBOMSerializer, InsumoSerializer, PedidoSerializer, UsuarioSerializer)

V, C, R = ROL_VENTAS, ROL_COCINERO, ROL_REPARTIDOR


def _usuario_json(user):
    return {'autenticado': True, 'username': user.get_username(), 'roles': roles_de(user),
            'superusuario': user.is_superuser, 'administrador': es_admin(user)}


# ------------------------------------------------------------- AUTENTICACIÓN
@method_decorator(ensure_csrf_cookie, name='dispatch')
@extend_schema(summary='Sesión actual', responses=inline_serializer('SesionActual', {
    'autenticado': serializers.BooleanField(), 'username': serializers.CharField(required=False),
    'roles': serializers.ListField(child=serializers.CharField(), required=False),
    'superusuario': serializers.BooleanField(required=False), 'administrador': serializers.BooleanField(required=False)}))
class MeView(APIView):
    """GET: sesión actual (y entrega la cookie CSRF al frontend)."""
    permission_classes = [AllowAny]

    def get(self, request):
        if request.user.is_authenticated:
            return Response(_usuario_json(request.user))
        return Response({'autenticado': False})


@extend_schema(summary='Iniciar sesión (5 fallos bloquean 15 min)', request=inline_serializer('Credenciales', {
    'username': serializers.CharField(), 'password': serializers.CharField()}),
    responses={200: OpenApiResponse(description='Sesión iniciada'), 400: OpenApiResponse(description='Credenciales incorrectas'),
               429: OpenApiResponse(description='Demasiados intentos fallidos')})
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        try:   # django-axes bloquea tras varios intentos fallidos (usuario + IP)
            user = authenticate(request._request, username=request.data.get('username'),
                                password=request.data.get('password'))
        except PermissionDenied:
            return Response({'detail': 'Demasiados intentos fallidos. Espera 15 minutos e inténtalo de nuevo.'},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        if user is None or not user.is_active:
            return Response({'detail': 'Usuario o contraseña incorrectos.'}, status=status.HTTP_400_BAD_REQUEST)
        login(request, user)          # crea la sesión (cookie sessionid)
        return Response(_usuario_json(user))


@extend_schema(summary='Cerrar sesión', request=None, responses={204: OpenApiResponse(description='Sesión cerrada')})
class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------- PEDIDOS
class PedidoViewSet(viewsets.ModelViewSet):
    serializer_class = PedidoSerializer
    permission_classes = [PermisoPorRol]
    roles_por_accion = {
        'list': {V, C, R}, 'retrieve': {V, C, R}, 'kanban': {V, C, R},
        'create': {V}, 'update': {V}, 'partial_update': {V}, 'destroy': {V},
        'cambiar_estado': {V, C},
    }

    def get_queryset(self):
        return Pedido.objects.prefetch_related('detalles__insumo')

    def perform_create(self, serializer):
        serializer.save(creado_por=self.request.user)

    def perform_destroy(self, instance):
        if instance.insumos_descontados:
            raise ValidationError('No se puede eliminar un pedido que ya consumió insumos.')
        instance.delete()

    @action(detail=False, methods=['get'])
    def kanban(self, request):
        """Pedidos agrupados por columna del tablero."""
        tablero = {valor: [] for valor, _ in EstadoPedido.choices}
        for pedido in self.get_queryset():
            tablero[pedido.estado].append(PedidoSerializer(pedido, context={'request': request}).data)
        return Response(tablero)

    @action(detail=True, methods=['post'])
    def cambiar_estado(self, request, pk=None):
        """Mueve la tarjeta. Al pasar a 'En Preparación' el modelo descuenta el inventario (BOM)."""
        pedido = self.get_object()
        ser = CambioEstadoSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        pedido.estado = ser.validated_data['estado']
        try:
            pedido.save()
        except DjangoValidationError as e:
            return Response({'detail': ' '.join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PedidoSerializer(pedido, context={'request': request}).data)


# ---------------------------------------------------------------- INVENTARIO
class InsumoViewSet(viewsets.ModelViewSet):
    queryset = Insumo.objects.all()
    serializer_class = InsumoSerializer
    permission_classes = [PermisoPorRol]
    roles_por_accion = {'list': {V, C}, 'retrieve': {V, C}, '*': {C}}   # el cocinero administra stock


# ----------------------------------------------------------------------- BOM
class DetalleBOMViewSet(viewsets.ModelViewSet):
    queryset = DetalleBOM.objects.select_related('pedido', 'insumo')
    serializer_class = DetalleBOMSerializer
    permission_classes = [PermisoPorRol]
    roles_por_accion = {'list': {V, C}, 'retrieve': {V, C}, '*': {V}}

    def _bloquear(self, pedido):
        if pedido.insumos_descontados:
            raise ValidationError('El pedido ya descontó insumos; el BOM no puede modificarse.')

    def perform_update(self, serializer):
        self._bloquear(serializer.instance.pedido)
        serializer.save()

    def perform_destroy(self, instance):
        self._bloquear(instance.pedido)
        instance.delete()


# ------------------------------------------------------------------ DESPACHO
class DespachoViewSet(viewsets.ModelViewSet):
    serializer_class = DespachoSerializer
    permission_classes = [PermisoPorRol]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    roles_por_accion = {
        'list': {V, R}, 'retrieve': {V, R},
        'create': {V}, 'update': {V}, 'partial_update': {V}, 'destroy': {V},
        'iniciar_ruta': {R}, 'confirmar': {R}, 'opciones': {V},
    }

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):      # generación del esquema de la documentación
            return Despacho.objects.none()
        qs = Despacho.objects.select_related('pedido', 'repartidor')
        u = self.request.user
        if tiene_rol(u, V):          # Ventas y Administrador ven todas las rutas
            return qs
        return qs.filter(repartidor=u)        # el repartidor solo ve SUS entregas

    @action(detail=False, methods=['get'])
    def opciones(self, request):
        """Datos para el formulario «Nuevo despacho»: pedidos Listos sin despacho y repartidores activos."""
        pedidos = Pedido.objects.filter(estado=EstadoPedido.LISTO, despacho__isnull=True).order_by('fecha_entrega')
        repartidores = User.objects.filter(is_active=True, groups__name=ROL_REPARTIDOR).order_by('username')
        return Response({
            'pedidos': [{'id': p.id, 'cliente': p.cliente_nombre, 'diseno': p.diseno,
                         'fecha_entrega': p.fecha_entrega} for p in pedidos],
            'repartidores': [{'id': u.id, 'username': u.get_username(), 'nombre': u.first_name} for u in repartidores],
        })

    def perform_destroy(self, instance):
        if instance.estado != Despacho.EstadoDespacho.PENDIENTE:
            raise ValidationError('Solo se puede quitar un despacho pendiente.')
        instance.delete()

    @action(detail=True, methods=['post'])
    def iniciar_ruta(self, request, pk=None):
        d = self.get_object()
        if d.estado != Despacho.EstadoDespacho.PENDIENTE:
            raise ValidationError('Solo se puede iniciar la ruta de un despacho pendiente.')
        d.estado = Despacho.EstadoDespacho.EN_RUTA
        d.save()
        return Response(self.get_serializer(d).data)

    @action(detail=True, methods=['post'])
    def confirmar(self, request, pk=None):
        """Confirma la entrega con foto (multipart) o firma digital (base64)."""
        d = self.get_object()
        if d.estado != Despacho.EstadoDespacho.EN_RUTA:
            raise ValidationError('Primero debes iniciar la ruta para confirmar la entrega.')
        ser = ConfirmarEntregaSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data.get('comprobante_foto'):
            d.comprobante_foto = ser.validated_data['comprobante_foto']
        d.firma_digital = ser.validated_data.get('firma_digital', d.firma_digital)
        d.estado = Despacho.EstadoDespacho.ENTREGADO
        d.save()
        return Response(self.get_serializer(d).data)


# ------------------------------------------------------------------- USUARIOS
class UsuarioViewSet(viewsets.ModelViewSet):
    """Gestión de usuarios y roles desde el panel. Solo el rol Administrador (o superusuario).
    No hay DELETE: los usuarios se desactivan para conservar el historial."""
    serializer_class = UsuarioSerializer
    permission_classes = [PermisoPorRol]
    roles_por_accion = {'*': {ROL_ADMIN}}
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        # los superusuarios de Django se administran solo desde /admin/
        return User.objects.filter(is_superuser=False).prefetch_related('groups').order_by('username')

    def perform_update(self, serializer):
        if serializer.instance.pk == self.request.user.pk:
            raise ValidationError('No puedes modificar tu propia cuenta desde aquí.')
        serializer.save()
