"""
models.py — Dulce Arte.
Entidades: Insumo, Pedido, DetalleBOM (modelo intermedio), Despacho.
Regla automática: al pasar un Pedido a "En Preparación" (o posterior) se
descuenta el stock de cada insumo según su BOM, una sola vez (idempotente).
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone


class EstadoPedido(models.TextChoices):
    """Columnas EXACTAS del tablero Kanban (el orden define el flujo)."""
    RECIBIDO = 'RECIBIDO', 'Recibido'
    EN_PREPARACION = 'EN_PREPARACION', 'En Preparación'
    HORNEADO_DECORADO = 'HORNEADO_DECORADO', 'Horneado/Decorado'
    CONTROL_CALIDAD = 'CONTROL_CALIDAD', 'Control de Calidad'
    LISTO = 'LISTO', 'Listo'


# ---------------------------------------------------------------- INVENTARIO
class Insumo(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    unidad_medida = models.CharField(max_length=20, default='kg', help_text='kg, g, lt, unidad...')
    stock_disponible = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(Decimal('0'))])
    stock_minimo = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, help_text='Bajo este valor se marca como stock bajo')
    costo_unitario = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(Decimal('0'))],
        help_text='Costo por unidad de medida (se usa para cotizar el pedido)')

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Insumo'
        verbose_name_plural = 'Insumos (inventario)'

    @property
    def bajo_stock(self):
        return self.stock_disponible <= self.stock_minimo

    def __str__(self):
        return f'{self.nombre} ({self.stock_disponible} {self.unidad_medida})'


# -------------------------------------------------------------------- PEDIDO
class Pedido(models.Model):
    cliente_nombre = models.CharField(max_length=150)
    cliente_telefono = models.CharField(max_length=30, blank=True)
    ingredientes = models.TextField(help_text='Ingredientes / sabores solicitados por el cliente')
    diseno = models.TextField('diseño', help_text='Descripción del diseño personalizado')
    fecha_entrega = models.DateTimeField('fecha y hora de entrega')
    precio_cotizado = models.DecimalField(
        max_digits=10, decimal_places=0, default=0, validators=[MinValueValidator(Decimal('0'))])
    estado = models.CharField(
        max_length=20, choices=EstadoPedido.choices, default=EstadoPedido.RECIBIDO, db_index=True)

    # BOM: relación M2M con modelo intermedio DetalleBOM (cantidad por insumo)
    insumos = models.ManyToManyField(Insumo, through='DetalleBOM', related_name='pedidos')

    # Marca de idempotencia: evita descontar dos veces el mismo pedido
    insumos_descontados = models.BooleanField(default=False, editable=False)

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='pedidos')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fecha_entrega']
        verbose_name = 'Pedido personalizado'
        verbose_name_plural = 'Pedidos personalizados'

    def __str__(self):
        return f'Pedido #{self.pk} — {self.cliente_nombre}'

    @property
    def costo_estimado(self):
        """Costo de los insumos del BOM (cantidad x costo unitario)."""
        return sum((d.cantidad * d.insumo.costo_unitario
                    for d in self.detalles.select_related('insumo')), Decimal('0'))

    def clean(self):
        if self._state.adding and self.fecha_entrega and self.fecha_entrega < timezone.now():
            raise ValidationError({'fecha_entrega': 'La fecha de entrega no puede estar en el pasado.'})

    # ---- Lógica automática de inventario -----------------------------------
    @transaction.atomic
    def descontar_insumos(self):
        """Descuenta del inventario los insumos del BOM. Idempotente."""
        if self.insumos_descontados:
            return
        detalles = list(self.detalles.select_related('insumo'))
        if not detalles:
            raise ValidationError(
                'El pedido no tiene Lista de Materiales (BOM): agrega los insumos antes de pasarlo a preparación.')

        # Bloquea las filas de inventario para evitar carreras entre cocineros
        bloqueados = {i.pk: i for i in Insumo.objects.select_for_update().filter(
            pk__in=[d.insumo_id for d in detalles])}

        faltantes = [
            f'{d.insumo.nombre} (necesita {d.cantidad}, hay {bloqueados[d.insumo_id].stock_disponible})'
            for d in detalles if bloqueados[d.insumo_id].stock_disponible < d.cantidad]
        if faltantes:
            raise ValidationError('Stock insuficiente: ' + '; '.join(faltantes))

        for d in detalles:  # F() => resta atómica en la BD
            Insumo.objects.filter(pk=d.insumo_id).update(
                stock_disponible=F('stock_disponible') - d.cantidad)

        Pedido.objects.filter(pk=self.pk).update(insumos_descontados=True)
        self.insumos_descontados = True

    def save(self, *args, **kwargs):
        """Override de save(): si el estado deja de ser 'Recibido', descuenta insumos.
        Todo en una transacción: si falta stock, se revierte también el cambio de estado."""
        with transaction.atomic():
            if self.pk:  # el tablero solo avanza de a un paso (sin saltos ni retrocesos)
                previo = Pedido.objects.filter(pk=self.pk).values_list('estado', flat=True).first()
                if previo and previo != self.estado:
                    orden = [e for e, _ in EstadoPedido.choices]
                    if orden.index(self.estado) != orden.index(previo) + 1:
                        raise ValidationError(
                            'Solo se puede avanzar al siguiente estado del Kanban (sin saltos ni retrocesos).')
            super().save(*args, **kwargs)
            if self.estado != EstadoPedido.RECIBIDO and not self.insumos_descontados:
                self.descontar_insumos()


# ----------------------------------------------------------------------- BOM
class DetalleBOM(models.Model):
    """Modelo intermedio: cuántas unidades de un insumo requiere un pedido."""
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='detalles')
    insumo = models.ForeignKey(Insumo, on_delete=models.PROTECT, related_name='usos_bom')
    cantidad = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])

    class Meta:
        unique_together = ('pedido', 'insumo')
        verbose_name = 'Línea de BOM'
        verbose_name_plural = 'Lista de materiales (BOM)'

    def clean(self):
        if self.pedido_id and self.pedido.insumos_descontados and not self.pk:
            raise ValidationError('El pedido ya descontó insumos; no se pueden agregar líneas al BOM.')

    def __str__(self):
        return f'{self.cantidad} {self.insumo.unidad_medida} de {self.insumo.nombre}'


# ------------------------------------------------------------------ DESPACHO
class Despacho(models.Model):
    class EstadoDespacho(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        EN_RUTA = 'EN_RUTA', 'En ruta'
        ENTREGADO = 'ENTREGADO', 'Entregado'

    pedido = models.OneToOneField(Pedido, on_delete=models.CASCADE, related_name='despacho')
    repartidor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='despachos', help_text='Usuario del grupo Repartidor')
    direccion_entrega = models.CharField(max_length=255)
    fecha_ruta = models.DateField(default=timezone.localdate)
    orden_ruta = models.PositiveSmallIntegerField(default=1, help_text='Posición en la ruta del día')
    estado = models.CharField(
        max_length=12, choices=EstadoDespacho.choices, default=EstadoDespacho.PENDIENTE)
    # Confirmación: comprobante fotográfico O firma digital (base64 del canvas)
    comprobante_foto = models.ImageField(upload_to='comprobantes/%Y/%m/', null=True, blank=True)
    firma_digital = models.TextField(blank=True, help_text='Firma en base64 (data URL)')
    entregado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['fecha_ruta', 'orden_ruta']
        verbose_name = 'Despacho'
        verbose_name_plural = 'Despachos / rutas'

    def clean(self):
        if self.estado == self.EstadoDespacho.ENTREGADO and not (self.comprobante_foto or self.firma_digital):
            raise ValidationError('Para marcar como Entregado se requiere comprobante fotográfico o firma digital.')

    def save(self, *args, **kwargs):
        if self.estado == self.EstadoDespacho.ENTREGADO and not self.entregado_en:
            self.entregado_en = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Despacho pedido #{self.pedido_id} — {self.get_estado_display()}'
