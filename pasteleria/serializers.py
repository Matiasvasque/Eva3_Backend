"""serializers.py — Dulce Arte."""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework import serializers

from .models import DetalleBOM, Despacho, EstadoPedido, Insumo, Pedido
from .permissions import ROL_ADMIN, ROL_REPARTIDOR, ROLES_TODOS, grupo_administrador, sincronizar_staff

MARGEN_COTIZACION = Decimal('2.5')   # precio sugerido = costo de insumos x 2,5


class InsumoSerializer(serializers.ModelSerializer):
    bajo_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Insumo
        fields = ['id', 'nombre', 'unidad_medida', 'stock_disponible', 'stock_minimo', 'costo_unitario', 'bajo_stock']


class DetalleBOMSerializer(serializers.ModelSerializer):
    """CRUD independiente de líneas BOM (/api/bom/)."""
    insumo_nombre = serializers.CharField(source='insumo.nombre', read_only=True)

    class Meta:
        model = DetalleBOM
        fields = ['id', 'pedido', 'insumo', 'insumo_nombre', 'cantidad']

    def validate_pedido(self, pedido):
        if pedido.insumos_descontados:
            raise serializers.ValidationError('El pedido ya descontó insumos; el BOM no puede modificarse.')
        return pedido


class DetalleBOMAnidadoSerializer(serializers.ModelSerializer):
    """Líneas BOM dentro del pedido (se crean junto con él)."""
    insumo_nombre = serializers.CharField(source='insumo.nombre', read_only=True)
    unidad = serializers.CharField(source='insumo.unidad_medida', read_only=True)

    class Meta:
        model = DetalleBOM
        fields = ['id', 'insumo', 'insumo_nombre', 'unidad', 'cantidad']


class PedidoSerializer(serializers.ModelSerializer):
    bom = DetalleBOMAnidadoSerializer(many=True, source='detalles', required=False)
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    costo_estimado = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Pedido
        fields = ['id', 'cliente_nombre', 'cliente_telefono', 'ingredientes', 'diseno',
                  'fecha_entrega', 'precio_cotizado', 'estado', 'estado_display',
                  'costo_estimado', 'insumos_descontados', 'bom', 'creado_en']
        # El estado SOLO cambia por /cambiar_estado/ (así se aplica el flujo Kanban y el descuento de stock)
        read_only_fields = ['estado', 'insumos_descontados', 'creado_en']

    def validate_fecha_entrega(self, valor):
        cambia = self.instance is None or valor != self.instance.fecha_entrega
        if cambia and valor < timezone.now():
            raise serializers.ValidationError('La fecha de entrega no puede estar en el pasado.')
        return valor

    def validate_bom(self, lineas):
        ids = [l['insumo'].pk for l in lineas]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError('Un insumo no puede repetirse en el BOM.')
        return lineas

    @transaction.atomic
    def create(self, validated_data):
        lineas = validated_data.pop('detalles', [])
        if not validated_data.get('precio_cotizado'):   # cotización automática desde el BOM
            costo = sum((l['insumo'].costo_unitario * l['cantidad'] for l in lineas), Decimal('0'))
            validated_data['precio_cotizado'] = (costo * MARGEN_COTIZACION).quantize(Decimal('1'))
        pedido = Pedido.objects.create(**validated_data)
        for l in lineas:
            DetalleBOM.objects.create(pedido=pedido, **l)
        return pedido

    def update(self, instance, validated_data):
        validated_data.pop('detalles', None)   # el BOM se edita en /api/bom/
        return super().update(instance, validated_data)


class CambioEstadoSerializer(serializers.Serializer):
    estado = serializers.ChoiceField(choices=EstadoPedido.choices)


class DespachoSerializer(serializers.ModelSerializer):
    cliente = serializers.CharField(source='pedido.cliente_nombre', read_only=True)
    repartidor_nombre = serializers.CharField(source='repartidor.get_username', read_only=True)

    class Meta:
        model = Despacho
        fields = ['id', 'pedido', 'cliente', 'repartidor', 'repartidor_nombre', 'direccion_entrega',
                  'fecha_ruta', 'orden_ruta', 'estado', 'comprobante_foto', 'firma_digital', 'entregado_en']
        read_only_fields = ['estado', 'comprobante_foto', 'firma_digital', 'entregado_en']
        extra_kwargs = {'orden_ruta': {'required': False}, 'fecha_ruta': {'required': False}}

    def validate_pedido(self, pedido):
        if self.instance is None and pedido.estado != EstadoPedido.LISTO:
            raise serializers.ValidationError('Solo se despachan pedidos en estado "Listo".')
        return pedido

    def validate_repartidor(self, usuario):
        if usuario and (not usuario.is_active or not usuario.groups.filter(name=ROL_REPARTIDOR).exists()):
            raise serializers.ValidationError('El usuario elegido no es un repartidor activo.')
        return usuario

    def validate_fecha_ruta(self, fecha):
        if self.instance is None and fecha < timezone.localdate():
            raise serializers.ValidationError('La fecha de la ruta no puede estar en el pasado.')
        return fecha

    def validate_direccion_entrega(self, valor):
        if len(valor.strip()) < 5:
            raise serializers.ValidationError('Indica una dirección de entrega completa.')
        return valor.strip()

    def create(self, datos):
        # Si no se indica el orden, la parada va al final de la ruta de ese repartidor y día
        if 'orden_ruta' not in datos:
            fecha = datos.get('fecha_ruta') or timezone.localdate()
            mismas = Despacho.objects.filter(repartidor=datos.get('repartidor'), fecha_ruta=fecha)
            datos['orden_ruta'] = (mismas.aggregate(m=Max('orden_ruta'))['m'] or 0) + 1
        return super().create(datos)


class ConfirmarEntregaSerializer(serializers.Serializer):
    comprobante_foto = serializers.ImageField(required=False)
    firma_digital = serializers.CharField(required=False, allow_blank=True)

    def validate(self, datos):
        if not (datos.get('comprobante_foto') or datos.get('firma_digital')):
            raise serializers.ValidationError('Debes enviar un comprobante fotográfico o una firma digital.')
        return datos


class UsuarioSerializer(serializers.ModelSerializer):
    """Usuarios del sistema con un rol (grupo). La contraseña es de solo escritura."""
    rol = serializers.ChoiceField(choices=[(r, r) for r in ROLES_TODOS], required=False)
    password = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'rol', 'password', 'is_active', 'last_login']
        read_only_fields = ['last_login']

    def validate_password(self, valor):
        validate_password(valor)          # usa AUTH_PASSWORD_VALIDATORS de settings.py
        return valor

    def validate(self, datos):
        if self.instance is None and not (datos.get('password') and datos.get('rol')):
            raise serializers.ValidationError('Para crear un usuario debes indicar contraseña y rol.')
        return datos

    def to_representation(self, instancia):
        datos = super().to_representation(instancia)
        nombres = {g.name for g in instancia.groups.all()}
        datos['rol'] = next((r for r in ROLES_TODOS if r in nombres), '')
        return datos

    @transaction.atomic
    def create(self, datos):
        rol, clave = datos.pop('rol'), datos.pop('password')
        usuario = User(**datos)
        usuario.set_password(clave)
        usuario.save()
        usuario.groups.set([grupo_administrador() if rol == ROL_ADMIN else Group.objects.get_or_create(name=rol)[0]])
        sincronizar_staff(usuario)        # solo el rol Administrador puede abrir /admin/
        return usuario

    @transaction.atomic
    def update(self, instancia, datos):
        rol, clave = datos.pop('rol', None), datos.pop('password', None)
        instancia = super().update(instancia, datos)
        if clave:
            instancia.set_password(clave)
            instancia.save()
        if rol:
            instancia.groups.set([grupo_administrador() if rol == ROL_ADMIN else Group.objects.get_or_create(name=rol)[0]])
            sincronizar_staff(instancia)
        return instancia
