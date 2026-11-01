# Registro de uso de IA — Dulce Arte

Herramienta: Claude (Anthropic). Usé la IA como apoyo para evaluar, programar y probar el proyecto;
revisé el código, lo ejecuté y soy responsable de entenderlo y defenderlo.

| # | Prompt (resumen) | Resultado | Qué verifiqué / ajusté |
|---|---|---|---|
| 1 | Corregir brechas de reglas de negocio y seguridad | Validaciones, permisos por rol, descuento idempotente | Probé cada regla con pruebas automáticas |
| 2 | Diseño visual crema/chocolate/rosa/dorado | Primera versión como tienda online | **Rechazada**: el proyecto es un sistema interno, no una tienda |
| 3 | Rehacer como panel interno (Kanban, bodega, rutas) | `index.html` con roles | Probé con los 3 roles y en móvil |
| 4 | Entregar todos los archivos completos | Zip del proyecto | Lo descomprimí y ejecuté migraciones |
| 5 | Comandos para recrear la base PostgreSQL | Comandos `DROP/CREATE DATABASE` | Los ejecuté en mi equipo |
| 6 | Datos de prueba | Comando `cargar_demo` | Revisé que los datos aparezcan en el panel |
| 7 | Arreglar 404, mantener admin y API root, rol Administrador, admin más bonito | Redirección, rol propio, `/api/usuarios/`, pestaña Equipo, admin con estilo | Probé permisos (403 para otros roles) |
| 8 | Revisión final contra la rúbrica | README, este registro y 12 pruebas | Ejecuté `python manage.py test` |

## Reflexión
La IA aceleró la escritura de código repetitivo, pero se equivocó al interpretar el proyecto como tienda
y en un cálculo de puntaje; ambos errores los detecté yo al revisar contra el enunciado.
Todo el código lo leí y puedo explicar el flujo del Kanban, el BOM y el descuento de stock.
