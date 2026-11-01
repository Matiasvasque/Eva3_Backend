"""python manage.py crear_roles [--demo]  -> crea los grupos y (opcional) usuarios de prueba."""
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from pasteleria.permissions import ROLES_TODOS, grupo_administrador, sincronizar_staff


class Command(BaseCommand):
    help = 'Crea los grupos Ventas, Cocinero, Repartidor y Administrador (y usuarios demo con --demo).'

    def add_arguments(self, parser):
        parser.add_argument('--demo', action='store_true', help='Crea ventas1/cocinero1/repartidor1/admin1 (clave Demo1234!)')

    def handle(self, *args, **opts):
        for rol in ROLES_TODOS:
            _, creado = Group.objects.get_or_create(name=rol)
            self.stdout.write(f'Grupo {rol}: {"creado" if creado else "ya existía"}')
        grupo_administrador()      # el rol Administrador recibe permisos sobre los modelos de la pastelería
        if opts['demo']:
            for rol, username in zip(ROLES_TODOS, ('ventas1', 'cocinero1', 'repartidor1', 'admin1')):
                u, creado = User.objects.get_or_create(username=username)   
                if creado:
                    u.set_password('Demo1234!')
                    u.save()
                u.groups.add(Group.objects.get(name=rol))
                sincronizar_staff(u)     # Administrador -> is_staff (abre /admin/); los demás no
                self.stdout.write(f'Usuario {username} -> {rol}')
