"""Lo que enseña la tienda de módulos: los ajustes generales y, de cada módulo, lo que dice su manifiesto."""
from .modules import REGISTRY


def f(key, label, type="str", help="", **kw):
    return {"key": key, "label": label, "type": type, "help": help, **kw}


GENERAL = [
    f("name", "Nombre del servidor", help="Sale en la app y en los avisos"),
    f("timezone", "Zona horaria", help="Para las tareas programadas, p. ej. Europe/Madrid"),
    f("disks", "Discos a mostrar", "list", "Puntos de montaje (admite *). Vacío = los discos reales"),
    f("disk_alert_percent", "Avisar con el disco al (%)", "int"),
    f("push_contact", "Contacto para los avisos push", help="mailto:tu@correo (lo pide el estándar Web Push)"),
]

# Lo de cada módulo viene de su manifiesto (app/modules/<nombre>/__init__.py)
CATALOG = {name: m.catalog() for name, m in REGISTRY.items()}


def secret_keys(module: str) -> set:
    return REGISTRY[module].secret_keys()
