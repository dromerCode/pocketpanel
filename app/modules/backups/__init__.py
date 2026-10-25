from ...module import Module, field

MODULE = Module(
    icon="⛁", title="Backups",
    desc="Copia incremental diaria de una carpeta a otra máquina por SSH, y restaurar por app.",
    order=50,
    fields=[
        field("source", "Carpeta a copiar", help="Cada subcarpeta se puede restaurar por separado", required=True),
        field("dest", "Destino", help="usuario@host:/ruta/absoluta", required=True),
        field("ssh_key", "Clave SSH para el destino", help="Ruta en el servidor. Vacío = la de tu usuario"),
        field("ssh_options", "Opciones de SSH", help="p. ej. -p 2222"),
        field("at", "Hacer la copia a las", "time", default="04:00"),
        field("keep_days", "Días que se guardan", "int", default=7),
        field("excludes", "No copiar", "list", "Patrones de rsync: cache/, *.log…",
              default=["cache/", "Cache/", "logs/", "log/", "*.log", "transcodes/"]),
    ],
)
