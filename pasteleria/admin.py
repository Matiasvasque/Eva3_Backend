"""
admin.py — Django Admin avanzado + templates HTML personalizados.
Templates sobrescritos (carpeta templates/admin/...):
  - admin/base_site.html                          -> marca/encabezado Dulce Arte
  - admin/pasteleria/pedido/change_form.html     -> barra de progreso Kanban + resumen BOM
  - admin/pasteleria/pedido/change_list.html     -> contadores por columna del Kanban
"""
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Count, F
from django.utils import timezone
from django.utils.html import format_html

from .models import DetalleBOM, Despacho, EstadoPedido, Insumo, Pedido

ORDEN = [e for e, _ in EstadoPedido.choices]
COLORES = {   # misma paleta que el panel: crema / chocolate / rosa / dorado
    'RECIBIDO': '#9a8878', 'EN_PREPARACION': '#c9a24b', 'HORNEADO_DECORADO': '#e0902f',
    'CONTROL_CALIDAD': '#c0587a', 'LISTO': '#6f9455',
}


class DetalleBOMInline(admin.TabularInline):
    model = DetalleBOM
    extra = 1
    autocomplete_fields = ['insumo']


class DespachoInline(admin.StackedInline):
    model = Despacho
    extra = 0
    max_num = 1
    fields = ('repartidor', 'direccion_entrega', 'fecha_ruta', 'orden_ruta', 'estado',
              'comprobante_foto', 'firma_digital')


@admin.register(Insumo)
class InsumoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'unidad_medida', 'stock_disponible', 'stock_minimo', 'costo_unitario', 'nivel_stock')
    list_filter = ('unidad_medida',)
    search_fields = ('nombre',)          # requerido por autocomplete_fields del BOM
    list_editable = ('stock_disponible',)
    ordering = ('nombre',)

    @admin.display(description='Nivel')
    def nivel_stock(self, obj):
        color, texto = ('#b3261e', 'BAJO') if obj.bajo_stock else ('#4f6f3b', 'OK')
        return format_html('<b style="color:{}">{}</b>', color, texto)


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'cliente_nombre', 'estado_badge', 'fecha_entrega',
                    'precio_cotizado', 'insumos_descontados', 'creado_por')
    list_filter = ('estado', 'insumos_descontados', 'fecha_entrega')
    search_fields = ('cliente_nombre', 'cliente_telefono', 'diseno', 'ingredientes')
    date_hierarchy = 'fecha_entrega'
    inlines = [DetalleBOMInline, DespachoInline]
    actions = ['avanzar_estado']
    readonly_fields = ('insumos_descontados', 'costo_estimado', 'creado_por', 'creado_en')

    # >>> Templates personalizados (criterio 2 de la rúbrica) <<<
    change_form_template = 'admin/pasteleria/pedido/change_form.html'
    change_list_template = 'admin/pasteleria/pedido/change_list.html'

    def get_readonly_fields(self, request, obj=None):
        base = super().get_readonly_fields(request, obj)
        # Un pedido nuevo siempre nace "Recibido": primero se arma el BOM, luego se avanza.
        return base + ('estado',) if obj is None else base

    @admin.display(description='Estado', ordering='estado')
    def estado_badge(self, obj):
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;border-radius:12px;font-size:11px">{}</span>',
            COLORES[obj.estado], obj.get_estado_display())

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creado_por = request.user
        try:
            super().save_model(request, obj, form, change)   # aquí corre el descuento de stock
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))

    @admin.action(description='Avanzar al siguiente estado del Kanban')
    def avanzar_estado(self, request, queryset):
        for pedido in queryset:
            i = ORDEN.index(pedido.estado)
            if i == len(ORDEN) - 1:
                continue
            pedido.estado = ORDEN[i + 1]
            try:
                pedido.save()
            except ValidationError as e:
                messages.error(request, f'Pedido #{pedido.pk}: ' + ' '.join(e.messages))

    # ---- datos extra para los templates --------------------------------------
    def changelist_view(self, request, extra_context=None):
        conteo = dict(Pedido.objects.values_list('estado').annotate(n=Count('id')))
        extra_context = extra_context or {}
        extra_context['resumen_kanban'] = [
            {'nombre': nombre, 'total': conteo.get(valor, 0), 'color': COLORES[valor]}
            for valor, nombre in EstadoPedido.choices]
        return super().changelist_view(request, extra_context=extra_context)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        pedido = Pedido.objects.filter(pk=object_id).first()
        if pedido:
            actual = ORDEN.index(pedido.estado)
            extra_context['pasos'] = [
                {'nombre': nombre, 'clase': 'hecho' if i < actual else 'actual' if i == actual else 'pendiente'}
                for i, (_, nombre) in enumerate(EstadoPedido.choices)]
            extra_context['bom_resumen'] = pedido.detalles.select_related('insumo')
        return super().change_view(request, object_id, form_url, extra_context=extra_context)


@admin.register(DetalleBOM)
class DetalleBOMAdmin(admin.ModelAdmin):
    list_display = ('pedido', 'insumo', 'cantidad')
    list_filter = ('insumo',)
    search_fields = ('pedido__cliente_nombre', 'insumo__nombre')
    autocomplete_fields = ['insumo']


@admin.register(Despacho)
class DespachoAdmin(admin.ModelAdmin):
    list_display = ('pedido', 'repartidor', 'fecha_ruta', 'orden_ruta', 'estado', 'vista_previa')
    list_filter = ('estado', 'fecha_ruta', 'repartidor')
    search_fields = ('pedido__cliente_nombre', 'direccion_entrega')
    readonly_fields = ('vista_previa', 'entregado_en')

    @admin.display(description='Comprobante')
    def vista_previa(self, obj):
        if obj.comprobante_foto:
            return format_html('<img src="{}" style="height:60px;border-radius:6px">', obj.comprobante_foto.url)
        return '—'


# ----------------------------------------------------- INICIO DEL ADMIN (KPIs)
def _kpis():
    """Tarjetas de resumen que se muestran en la portada del Django Admin."""
    activos = Pedido.objects.exclude(estado=EstadoPedido.LISTO)
    return [
        {'nombre': 'Pedidos activos', 'valor': activos.count(), 'color': '#c9a24b'},
        {'nombre': 'Pedidos atrasados', 'valor': activos.filter(fecha_entrega__lt=timezone.now()).count(), 'color': '#b3261e'},
        {'nombre': 'Insumos con stock bajo', 'valor': Insumo.objects.filter(stock_disponible__lte=F('stock_minimo')).count(), 'color': '#e0902f'},
        {'nombre': 'Entregas pendientes de hoy', 'valor': Despacho.objects.filter(
            fecha_ruta=timezone.localdate()).exclude(estado=Despacho.EstadoDespacho.ENTREGADO).count(), 'color': '#6f9455'},
    ]


_indice_original = admin.site.index


def _indice_con_kpis(request, extra_context=None):
    return _indice_original(request, dict(extra_context or {}, kpis=_kpis()))


admin.site.index = _indice_con_kpis      # el template templates/admin/index.html pinta las tarjetas
