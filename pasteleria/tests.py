"""Pruebas de reglas de negocio y permisos. Ejecutar: python manage.py test"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import DetalleBOM, Insumo, Pedido, EstadoPedido
from .permissions import ROLES_TODOS


def usuario(nombre, rol):
    u = User.objects.create_user(nombre, password='Demo1234!')
    g, _ = Group.objects.get_or_create(name=rol)
    u.groups.add(g)
    return u


class ReglasDeNegocio(TestCase):
    def setUp(self):
        self.harina = Insumo.objects.create(nombre='Harina', stock_disponible=10, costo_unitario=1000)
        self.p = Pedido.objects.create(
            cliente_nombre='Ana', ingredientes='x', diseno='y',
            fecha_entrega=timezone.now() + timedelta(days=2))
        DetalleBOM.objects.create(pedido=self.p, insumo=self.harina, cantidad=Decimal('3'))

    def test_descuento_unico_al_salir_de_recibido(self):
        self.p.estado = EstadoPedido.EN_PREPARACION
        self.p.save()
        self.harina.refresh_from_db()
        self.assertEqual(self.harina.stock_disponible, Decimal('7.00'))
        self.p.estado = EstadoPedido.HORNEADO_DECORADO
        self.p.save()
        self.harina.refresh_from_db()
        self.assertEqual(self.harina.stock_disponible, Decimal('7.00'))  # no descuenta dos veces

    def test_stock_insuficiente_revierte_estado(self):
        self.harina.stock_disponible = 1
        self.harina.save()
        self.p.estado = EstadoPedido.EN_PREPARACION
        with self.assertRaises(ValidationError):
            self.p.save()
        self.p.refresh_from_db()
        self.assertEqual(self.p.estado, EstadoPedido.RECIBIDO)

    def test_sin_bom_no_avanza(self):
        q = Pedido.objects.create(cliente_nombre='B', ingredientes='x', diseno='y',
                                  fecha_entrega=timezone.now() + timedelta(days=1))
        q.estado = EstadoPedido.EN_PREPARACION
        with self.assertRaises(ValidationError):
            q.save()

    def test_no_se_permiten_saltos_ni_retrocesos(self):
        self.p.estado = EstadoPedido.LISTO
        with self.assertRaises(ValidationError):
            self.p.save()

    def test_fecha_pasada_rechazada(self):
        q = Pedido(cliente_nombre='C', ingredientes='x', diseno='y',
                   fecha_entrega=timezone.now() - timedelta(days=1))
        with self.assertRaises(ValidationError):
            q.full_clean()

    def test_costo_estimado(self):
        self.assertEqual(self.p.costo_estimado, Decimal('3000'))


class PermisosPorRol(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.u = {r: usuario(r.lower(), r) for r in ROLES_TODOS}

    def status(self, rol, url):
        self.c.force_authenticate(self.u[rol])
        return self.c.get(url).status_code

    def test_anonimo_recibe_403(self):
        self.c.force_authenticate(None)
        self.assertIn(self.c.get('/api/pedidos/').status_code, (401, 403))

    def test_usuarios_solo_admin(self):
        for rol in ('Ventas', 'Cocinero', 'Repartidor'):
            self.assertEqual(self.status(rol, '/api/usuarios/'), 403)
        self.assertEqual(self.status('Administrador', '/api/usuarios/'), 200)

    def test_repartidor_no_ve_insumos(self):
        self.assertEqual(self.status('Repartidor', '/api/insumos/'), 403)
        self.assertEqual(self.status('Cocinero', '/api/insumos/'), 200)

    def test_cocinero_no_crea_pedidos(self):
        self.c.force_authenticate(self.u['Cocinero'])
        r = self.c.post('/api/pedidos/', {'cliente_nombre': 'X'}, format='json')
        self.assertEqual(r.status_code, 403)


class RutasGenerales(TestCase):
    def test_url_inexistente_redirige(self):
        self.assertEqual(self.client.get('/cualquier-cosa').status_code, 302)

    def test_api_root_publico(self):
        self.assertEqual(self.client.get('/api/').status_code, 200)


class SeguridadLogin(TestCase):
    def test_bloqueo_tras_5_intentos_fallidos(self):
        usuario('ventas1', 'Ventas')
        c = APIClient()
        for _ in range(4):
            r = c.post('/api/auth/login/', {'username': 'ventas1', 'password': 'mala'}, format='json')
            self.assertEqual(r.status_code, 400)
        r = c.post('/api/auth/login/', {'username': 'ventas1', 'password': 'mala'}, format='json')
        self.assertEqual(r.status_code, 429)      # el 5.º intento fallido activa el bloqueo
        # ya bloqueado: ni siquiera la clave correcta entra
        r = c.post('/api/auth/login/', {'username': 'ventas1', 'password': 'Demo1234!'}, format='json')
        self.assertEqual(r.status_code, 429)

    def test_login_correcto_funciona(self):
        usuario('ventas1', 'Ventas')
        r = APIClient().post('/api/auth/login/', {'username': 'ventas1', 'password': 'Demo1234!'}, format='json')
        self.assertEqual(r.status_code, 200)


class CrearDespachos(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.ventas = usuario('ventas1', 'Ventas')
        self.rep = usuario('repartidor1', 'Repartidor')
        self.cocinero = usuario('cocinero1', 'Cocinero')
        ins = Insumo.objects.create(nombre='Harina', stock_disponible=50)
        self.listo = self._pedido('Ana', ins, LISTO=True)
        self.recibido = self._pedido('Beto', ins)
        self.datos = {'pedido': self.listo.pk, 'repartidor': self.rep.pk,
                      'direccion_entrega': 'Los Leones 1234, Providencia'}

    def _pedido(self, nombre, ins, LISTO=False):
        p = Pedido.objects.create(cliente_nombre=nombre, ingredientes='x', diseno='y',
                                  fecha_entrega=timezone.now() + timedelta(days=1))
        DetalleBOM.objects.create(pedido=p, insumo=ins, cantidad=1)
        if LISTO:
            for e in list(EstadoPedido)[1:]:
                p.estado = e
                p.save()
        return p

    def test_ventas_crea_despacho_con_orden_automatico(self):
        self.c.force_authenticate(self.ventas)
        r = self.c.post('/api/despachos/', self.datos, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['orden_ruta'], 1)

    def test_solo_pedidos_listos(self):
        self.c.force_authenticate(self.ventas)
        r = self.c.post('/api/despachos/', {**self.datos, 'pedido': self.recibido.pk}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_un_solo_despacho_por_pedido(self):
        self.c.force_authenticate(self.ventas)
        self.c.post('/api/despachos/', self.datos, format='json')
        self.assertEqual(self.c.post('/api/despachos/', self.datos, format='json').status_code, 400)

    def test_repartidor_debe_ser_del_grupo(self):
        self.c.force_authenticate(self.ventas)
        r = self.c.post('/api/despachos/', {**self.datos, 'repartidor': self.cocinero.pk}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_cocinero_y_repartidor_no_crean(self):
        for u in (self.cocinero, self.rep):
            self.c.force_authenticate(u)
            self.assertEqual(self.c.post('/api/despachos/', self.datos, format='json').status_code, 403)
            self.assertEqual(self.c.get('/api/despachos/opciones/').status_code, 403)

    def test_opciones_lista_solo_listos_sin_despacho(self):
        self.c.force_authenticate(self.ventas)
        r = self.c.get('/api/despachos/opciones/')
        self.assertEqual([p['id'] for p in r.data['pedidos']], [self.listo.pk])
        self.assertEqual([u['id'] for u in r.data['repartidores']], [self.rep.pk])

    def test_solo_se_quita_un_despacho_pendiente(self):
        self.c.force_authenticate(self.ventas)
        d = self.c.post('/api/despachos/', self.datos, format='json').data['id']
        from .models import Despacho
        Despacho.objects.filter(pk=d).update(estado='EN_RUTA')
        self.assertEqual(self.c.delete(f'/api/despachos/{d}/').status_code, 400)
        Despacho.objects.filter(pk=d).update(estado='PENDIENTE')
        self.assertEqual(self.c.delete(f'/api/despachos/{d}/').status_code, 204)


class DocsYAdmin(TestCase):
    def setUp(self):
        self.c = APIClient()

    def test_docs_solo_administrador(self):
        self.c.force_authenticate(None)
        self.assertIn(self.c.get('/api/docs/').status_code, (401, 403))
        for rol in ('Ventas', 'Cocinero', 'Repartidor'):
            self.c.force_authenticate(usuario(rol.lower(), rol))
            self.assertEqual(self.c.get('/api/docs/').status_code, 403)
            self.assertEqual(self.c.get('/api/schema/').status_code, 403)
        self.c.force_authenticate(usuario('admin1', 'Administrador'))
        self.assertEqual(self.c.get('/api/docs/').status_code, 200)
        self.assertEqual(self.c.get('/api/schema/').status_code, 200)

    def test_rol_administrador_abre_django_admin(self):
        from .permissions import grupo_administrador, sincronizar_staff
        grupo_administrador()
        a = usuario('admin1', 'Administrador')
        sincronizar_staff(a)
        v = usuario('ventas1', 'Ventas')
        sincronizar_staff(v)
        self.assertTrue(User.objects.get(pk=a.pk).is_staff)
        self.assertFalse(User.objects.get(pk=v.pk).is_staff)
        self.client.force_login(a)
        self.assertEqual(self.client.get('/admin/pasteleria/pedido/').status_code, 200)
        self.client.force_login(v)
        self.assertEqual(self.client.get('/admin/pasteleria/pedido/').status_code, 302)

    def test_crear_admin_desde_api_lo_hace_staff(self):
        from .permissions import grupo_administrador
        grupo_administrador()
        self.c.force_authenticate(usuario('admin1', 'Administrador'))
        r = self.c.post('/api/usuarios/', {'username': 'nuevo', 'password': 'Clave-Segura-99', 'rol': 'Administrador'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(User.objects.get(username='nuevo').is_staff)
        r = self.c.patch(f"/api/usuarios/{r.data['id']}/", {'rol': 'Ventas'}, format='json')
        self.assertFalse(User.objects.get(username='nuevo').is_staff)
