# Dulce Arte — Trazabilidad y gestión de pedidos (EVA 3 Desarrollo Backend)

Sistema interno para una pastelería artesanal: pedidos personalizados con tablero Kanban,
lista de materiales (BOM) con descuento automático de inventario, rutas de despacho y roles.
Stack: Django 5 + Django REST Framework + PostgreSQL (despliegue en AWS EC2).

## Instalación local
```bash
python -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # y editar claves / DB
python manage.py migrate                                # incluye las tablas de django-axes
python manage.py crear_roles --demo                     # grupos + usuarios de prueba (clave Demo1234!)
python manage.py cargar_demo                            # datos de ejemplo (--reset para reiniciar)
python manage.py createsuperuser                        # acceso a /admin/
python manage.py runserver
```
Base de datos: `CREATE DATABASE dulce_arte;` y credenciales en `.env` (DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT).

## Rutas
| Ruta | Descripción |
|---|---|
| `/` | Panel interno (Tablero, Bodega, Rutas, Equipo) |
| `/admin/` | Django Admin personalizado (solo Administrador y superusuario; botón «Django Admin» en el panel) |
| `/api/docs/` | Documentación Swagger de la API (solo Administrador y superusuario; botón «API Docs»). También `/api/redoc/` y `/api/schema/` |
| `/api/` | Raíz de la API (pública) |
| `/api-auth/login/` | Login para la API navegable |
| Cualquier otra | Redirige a `/` |

## Roles (grupos)
| Rol | Puede |
|---|---|
| Ventas | Crear/editar pedidos y BOM, crear y quitar despachos, ver rutas |
| Cocinero | Ver pedidos, avanzar el Kanban, gestionar inventario |
| Repartidor | Ver sus despachos, iniciar ruta y confirmar entrega (foto o firma) |
| Administrador | Todo lo anterior + gestionar usuarios (pestaña Equipo), abrir el Django Admin y ver la documentación de la API. Distinto del superusuario de Django: sus permisos se limitan a los modelos de la pastelería |

## Reglas de negocio
- Kanban de 5 estados, solo avanza un paso (sin saltos ni retrocesos).
- Al salir de *Recibido* se descuenta el stock según el BOM, una sola vez y en transacción; si falta stock se revierte todo.
- No se aceptan fechas de entrega pasadas ni precios negativos.
- Entrega confirmada solo con comprobante fotográfico o firma digital.
- Despachos: se crean desde el panel (pestaña Rutas → «Nuevo despacho»). Solo pedidos en *Listo*, uno por pedido,
  repartidor del grupo Repartidor, fecha no pasada y orden de parada automático. Solo se pueden quitar los pendientes.

## Seguridad
- Sesiones con cookie HttpOnly, SameSite=Lax y expiración de 8 h; CSRF activo; permisos por rol en cada acción.
- **Bloqueo por fuerza bruta (django-axes):** 5 intentos fallidos bloquean usuario+IP por 15 min, en el panel y en `/admin/`.
  Para desbloquear antes: `python manage.py axes_reset` (o `axes_reset_username NOMBRE`).
- Secretos en `.env`; validadores de contraseña de Django.
- Con HTTPS, poner `DJANGO_HTTPS=True` en `.env`: activa cookies seguras, redirección a https y HSTS.
  (No activarlo mientras se acceda por `http://IP`, porque el login dejaría de funcionar.)

## Pruebas
`python manage.py test pasteleria` (24 pruebas: reglas de negocio, permisos, bloqueo de login, despachos y accesos de administrador).

## Despliegue en AWS EC2
- URL pública: **http://54.172.70.188/**  
- Gunicorn + WhiteNoise; `DJANGO_ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS` con la IP; `python manage.py collectstatic`.

## Uso de IA
Ver `prompts_ia.md`.
