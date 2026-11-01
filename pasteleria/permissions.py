"""
permissions.py — Permisos por rol (grupos de Django).
Cada ViewSet declara `roles_por_accion = {'list': {...}, '*': {...}}`.
El rol "Administrador" (grupo propio del sistema, distinto del superusuario de Django Admin)
y el superusuario siempre tienen acceso. Sin regla para la acción => se deniega.
"""
from django.contrib.auth.models import Group, Permission
from rest_framework.permissions import BasePermission

ROL_VENTAS = 'Ventas'
ROL_COCINERO = 'Cocinero'
ROL_REPARTIDOR = 'Repartidor'
ROL_ADMIN = 'Administrador'
ROLES = (ROL_VENTAS, ROL_COCINERO, ROL_REPARTIDOR)      # roles operativos
ROLES_TODOS = ROLES + (ROL_ADMIN,)


def roles_de(user):
    return list(user.groups.values_list('name', flat=True)) if user.is_authenticated else []


def es_admin(user):
    """Superusuario de Django o miembro del grupo Administrador (acceso total al panel y a la API)."""
    return bool(user.is_authenticated and (user.is_superuser or user.groups.filter(name=ROL_ADMIN).exists()))


def tiene_rol(user, *roles):
    return bool(user.is_authenticated and (es_admin(user) or user.groups.filter(name__in=roles).exists()))


def grupo_administrador():
    """Grupo Administrador con permisos sobre todos los modelos de la pastelería (para entrar al Django Admin)."""
    grupo, _ = Group.objects.get_or_create(name=ROL_ADMIN)
    grupo.permissions.set(Permission.objects.filter(content_type__app_label='pasteleria'))
    return grupo


def sincronizar_staff(usuario):
    """Los miembros del grupo Administrador pueden abrir /admin/ (is_staff); el resto no."""
    if usuario.is_superuser:
        return
    debe = usuario.groups.filter(name=ROL_ADMIN).exists()
    if usuario.is_staff != debe:
        usuario.is_staff = debe
        usuario.save(update_fields=['is_staff'])


class SoloAdministrador(BasePermission):
    """Documentación de la API: solo rol Administrador o superusuario."""
    message = 'La documentación de la API es solo para administradores.'

    def has_permission(self, request, view):
        return es_admin(request.user)


class PermisoPorRol(BasePermission):
    message = 'Tu rol no tiene acceso a este recurso.'

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if es_admin(user):
            return True
        reglas = getattr(view, 'roles_por_accion', {})
        permitidos = reglas.get(getattr(view, 'action', None)) or reglas.get('*')
        return bool(permitidos) and user.groups.filter(name__in=permitidos).exists()
