"""python manage.py cargar_demo [--reset]
Carga datos de ejemplo: insumos, pedidos en cada columna del Kanban, rutas de hoy/mañana y entregas históricas."""
import datetime

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from pasteleria.models import DetalleBOM, Despacho, EstadoPedido, Insumo, Pedido

FIRMA = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='

INSUMOS = [  # nombre, unidad, stock, mínimo, costo unitario
    ('Harina de trigo', 'kg', 60, 10, 1200), ('Azúcar', 'kg', 4, 8, 1100), ('Azúcar flor', 'kg', 12, 3, 1900),
    ('Huevos', 'unidad', 180, 36, 180), ('Mantequilla', 'kg', 25, 5, 6500), ('Crema para batir', 'lt', 18, 4, 3200),
    ('Chocolate cobertura', 'kg', 15, 3, 9800), ('Cacao en polvo', 'kg', 5, 1, 7800), ('Leche', 'lt', 40, 8, 1000),
    ('Manjar', 'kg', 10, 2, 3600), ('Frutillas', 'kg', 6, 2, 4500), ('Frambuesas', 'kg', 2, 2, 9500),
    ('Fondant', 'kg', 9, 2, 5200), ('Esencia de vainilla', 'lt', 3, 0.5, 14000), ('Almendras', 'kg', 4, 1, 12000),
    ('Colorante alimentario', 'unidad', 20, 5, 1500),
]

# cliente, días hasta entrega, horas extra, diseño, BOM, pasos de Kanban (0=Recibido ... 4=Listo), precio
PEDIDOS = [
    ('María Fernández', 3, 0, 'Torta de boda de 3 pisos con flores de azúcar', [('Harina de trigo', 3), ('Huevos', 36), ('Mantequilla', 2.5), ('Fondant', 2)], 0, 145000),
    ('Constanza Muñoz', 2, 4, 'Torta de cumpleaños 15 años tema galaxia', [('Harina de trigo', 1.5), ('Fondant', 1), ('Colorante alimentario', 3), ('Huevos', 12)], 0, 62000),
    ('Empresa Andes Tech', 4, 0, '60 cupcakes con logo corporativo', [('Harina de trigo', 2), ('Azúcar flor', 1), ('Mantequilla', 1)], 0, 78000),
    ('Colegio San Andrés', 0, 6, 'Cupcakes con el logo del colegio', [('Harina de trigo', 1), ('Azúcar', 1)], 1, 32000),
    ('Familia Reyes', 1, 2, 'Torta de bautizo con angelitos', [('Harina de trigo', 1), ('Fondant', 0.8), ('Huevos', 10)], 1, 48000),
    ('Ana Pérez', -1, 0, 'Torta tres leches (atrasada)', [('Leche', 2), ('Huevos', 8), ('Crema para batir', 1)], 1, 22000),
    ('Pedro Soto', 1, 0, 'Torta de chocolate "Felices 30"', [('Chocolate cobertura', 1), ('Cacao en polvo', 0.3), ('Huevos', 12)], 2, 28000),
    ('Gimnasio Fuerza Sur', 1, 5, 'Torta con forma de mancuerna', [('Harina de trigo', 1.5), ('Fondant', 1), ('Chocolate cobertura', 0.5)], 2, 55000),
    ('Camila Rojas', 0, 5, 'Torta infantil de unicornio', [('Harina de trigo', 1), ('Mantequilla', 0.5), ('Colorante alimentario', 2)], 3, 41000),
    ('Restaurante El Parrón', 0, 7, 'Bandeja de 24 tartaletas de frutillas', [('Frutillas', 1.5), ('Crema para batir', 1), ('Harina de trigo', 1)], 3, 54000),
    ('Hotel Costanera', 0, 8, 'Bandeja de 40 petit fours', [('Chocolate cobertura', 0.5), ('Azúcar flor', 0.5), ('Almendras', 0.3)], 4, 120000),
    ('Lucía Vargas', 0, 2, 'Mini tortas de cumpleaños', [('Harina de trigo', 1), ('Manjar', 0.5)], 4, 26000),
    ('Matías Herrera', 0, 4, 'Torta de frambuesa y vainilla', [('Frambuesas', 0.5), ('Esencia de vainilla', 0.05), ('Harina de trigo', 1)], 4, 38000),
    ('Sofía Lagos', 0, 9, 'Torta de zanahoria con frosting (lista para despachar)', [('Harina de trigo', 1), ('Mantequilla', 0.5)], 4, 35000),
    ('Fundación Sonrisas', 2, 0, 'Torta solidaria 40 porciones', [('Harina de trigo', 2), ('Manjar', 1), ('Huevos', 14)], 0, 45000),
    ('Valentina Díaz', 5, 0, 'Torta de matrimonio civil minimalista', [('Harina de trigo', 1.5), ('Frutillas', 0.5), ('Crema para batir', 1)], 0, 69000),
]

# Entregas históricas (ya entregadas): cliente, días atrás, diseño, BOM, precio, dirección
HISTORICOS = [
    ('Jorge Castillo', 2, 'Torta de aniversario 25 años', [('Harina de trigo', 1), ('Huevos', 8)], 52000, 'Av. Apoquindo 4500, Las Condes'),
    ('Paula Araya', 3, 'Cheesecake de frutos rojos', [('Frambuesas', 0.4), ('Crema para batir', 1)], 36000, 'Gral. Bustamante 220, Providencia'),
    ('Café Central', 5, '30 alfajores artesanales', [('Harina de trigo', 1), ('Manjar', 0.6)], 24000, 'Merced 345, Santiago Centro'),
    ('Iván Salazar', 7, 'Torta de chocolate para 20 personas', [('Chocolate cobertura', 1), ('Huevos', 10)], 33000, 'Irarrázaval 2100, Ñuñoa'),
]


class Command(BaseCommand):
    help = 'Carga datos de ejemplo (insumos, pedidos en cada columna del Kanban, rutas y entregas).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Borra pedidos, despachos e insumos antes de cargar')

    def handle(self, *args, **opts):
        if opts['reset']:
            Despacho.objects.all().delete()
            Pedido.objects.all().delete()
            Insumo.objects.all().delete()
        elif Pedido.objects.exists() or Insumo.objects.exists():
            raise CommandError('Ya hay datos. Usa --reset para borrarlos y volver a cargar el ejemplo.')

        call_command('crear_roles', '--demo', verbosity=0)   # grupos + ventas1 / cocinero1 / repartidor1 / admin1
        ventas, repartidor = User.objects.get(username='ventas1'), User.objects.get(username='repartidor1')

        I = {}
        for nombre, unidad, stock, minimo, costo in INSUMOS:
            I[nombre] = Insumo.objects.create(nombre=nombre, unidad_medida=unidad, stock_disponible=stock,
                                              stock_minimo=minimo, costo_unitario=costo)

        ahora = timezone.now()
        orden = [e for e, _ in EstadoPedido.choices]

        def pedido(cliente, dias, horas, diseno, bom, pasos, precio):
            p = Pedido.objects.create(
                cliente_nombre=cliente, cliente_telefono='+56 9 %04d %04d' % (hash(cliente) % 9000 + 1000, hash(cliente[::-1]) % 9000 + 1000),
                ingredientes='Según BOM; sabores a elección del cliente', diseno=diseno, precio_cotizado=precio,
                fecha_entrega=ahora + datetime.timedelta(days=dias, hours=horas), creado_por=ventas)
            for nombre, cantidad in bom:
                DetalleBOM.objects.create(pedido=p, insumo=I[nombre], cantidad=cantidad)
            for i in range(pasos):          # avanza el Kanban paso a paso (descuenta insumos al pasar a En Preparación)
                p.estado = orden[i + 1]
                p.save()
            return p

        creados = {c: pedido(c, d, h, di, b, s, pr) for c, d, h, di, b, s, pr in PEDIDOS}

        hoy = timezone.localdate()
        ruta = [  # cliente, dirección, fecha de la ruta, orden, estado
            ('Hotel Costanera', 'Av. Costanera Center 100, Providencia', hoy, 1, Despacho.EstadoDespacho.EN_RUTA),
            ('Lucía Vargas', 'Los Leones 1234, Providencia', hoy, 2, Despacho.EstadoDespacho.PENDIENTE),
            ('Matías Herrera', 'Av. Vitacura 3800, Vitacura', hoy, 3, Despacho.EstadoDespacho.PENDIENTE),
            ('Camila Rojas', 'Pedro de Valdivia 950, Ñuñoa', hoy + datetime.timedelta(days=1), 1, Despacho.EstadoDespacho.PENDIENTE),
            ('Restaurante El Parrón', 'Av. Italia 1480, Ñuñoa', hoy + datetime.timedelta(days=1), 2, Despacho.EstadoDespacho.PENDIENTE),
        ]
        for cliente, direccion, fecha, orden_ruta, estado in ruta:
            Despacho.objects.create(pedido=creados[cliente], repartidor=repartidor, direccion_entrega=direccion,
                                    fecha_ruta=fecha, orden_ruta=orden_ruta, estado=estado)

        for cliente, atras, diseno, bom, precio, direccion in HISTORICOS:   # historial de entregas realizadas
            p = pedido(cliente, -atras, 0, diseno, bom, 4, precio)
            Despacho.objects.create(pedido=p, repartidor=repartidor, direccion_entrega=direccion,
                                    fecha_ruta=hoy - datetime.timedelta(days=atras), orden_ruta=1,
                                    estado=Despacho.EstadoDespacho.ENTREGADO, firma_digital=FIRMA)

        self.stdout.write(self.style.SUCCESS(
            f'Datos cargados: {Insumo.objects.count()} insumos, {Pedido.objects.count()} pedidos y '
            f'{Despacho.objects.count()} despachos. Usuarios demo: ventas1 / cocinero1 / repartidor1 / admin1 (Demo1234!)'))
