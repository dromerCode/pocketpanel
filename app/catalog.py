"""Lo que enseña la tienda de módulos: textos y campos de cada módulo y de los ajustes generales."""


def f(key, label, type="str", help="", **kw):
    return {"key": key, "label": label, "type": type, "help": help, **kw}


GENERAL = [
    f("name", "Nombre del servidor", help="Sale en la app y en los avisos"),
    f("timezone", "Zona horaria", help="Para las tareas programadas, p. ej. Europe/Madrid"),
    f("disks", "Discos a mostrar", "list", "Puntos de montaje (admite *). Vacío = los discos reales"),
    f("disk_alert_percent", "Avisar con el disco al (%)", "int"),
    f("push_contact", "Contacto para los avisos push", help="mailto:tu@correo (lo pide el estándar Web Push)"),
]

CATALOG = {
    "terminal": {
        "icon": "›_", "title": "Terminal", "desc": "Una shell en el servidor desde el móvil (bash y tmux).",
        "fields": [],
    },
    "actions": {
        "icon": "⚡", "title": "Acciones rápidas", "desc": "Botones que ejecutan tus comandos de actions.yml.",
        "fields": [],
    },
    "updates": {
        "icon": "⬆", "title": "Actualizaciones",
        "desc": "Busca imágenes nuevas cada día y actualiza contenedores con vuelta atrás si fallan.",
        "fields": [f("check_at", "Buscar cada día a las", "time")],
    },
    "claude": {
        "icon": "✳", "title": "Claude Code",
        "desc": "Chat con el Claude Code del servidor, botón de diagnóstico y resumen diario por push.",
        "fields": [
            f("home", "HOME de Claude", help="Vacío = el de tu usuario"),
            f("cwd", "Carpeta de trabajo", help="Vacío = igual que el HOME"),
            f("bin", "Ruta de claude", help="Vacío = HOME/.local/bin/claude (mírala con `which claude`)"),
            f("permission_mode", "Permisos", "choice", "El chat no puede preguntarte: con «auto» o «bypassPermissions» "
              "puede ejecutar comandos", choices=["", "default", "acceptEdits", "plan", "auto", "dontAsk",
                                                   "bypassPermissions"]),
            f("report_at", "Resumen diario a las", "time", "Vacío = sin resumen diario", nullable=True),
            f("report_notes", "Notas para el resumen", help="Cosas que Claude debe saber al revisar"),
            f("diagnosis", "Prompt del diagnóstico", help="Vacío = uno genérico"),
        ],
    },
    "backups": {
        "icon": "⛁", "title": "Backups",
        "desc": "Copia incremental diaria de una carpeta a otra máquina por SSH, y restaurar por app.",
        "fields": [
            f("source", "Carpeta a copiar", help="Cada subcarpeta se puede restaurar por separado"),
            f("dest", "Destino", help="usuario@host:/ruta/absoluta"),
            f("ssh_key", "Clave SSH para el destino", help="Ruta en el servidor. Vacío = la de tu usuario"),
            f("ssh_options", "Opciones de SSH", help="p. ej. -p 2222"),
            f("at", "Hacer la copia a las", "time"),
            f("keep_days", "Días que se guardan", "int"),
            f("excludes", "No copiar", "list", "Patrones de rsync: cache/, *.log…"),
        ],
    },
    "raid": {
        "icon": "◫", "title": "RAID", "desc": "Estado de un RAID mdadm y SMART de sus discos, con avisos.",
        "fields": [
            f("device", "Dispositivo"),
            f("ssh", "En otra máquina", help="Vacío = en este servidor; si no, usuario@host"),
            f("ssh_options", "Opciones de SSH"),
            f("sudo", "Usar sudo para mdadm/smartctl", "bool", "Necesita una regla en sudoers"),
        ],
    },
    "sites": {
        "icon": "◎", "title": "Webs y certificados",
        "desc": "Comprueba que tus webs responden y avisa si caen o si el certificado está a punto de caducar.",
        "fields": [
            f("urls", "Webs a vigilar", "list", "Una URL por línea: https://midominio.com, http://127.0.0.1:8096…"),
            f("interval", "Comprobar cada (minutos)", "int"),
            f("cert_warn_days", "Avisar si al certificado le quedan (días)", "int"),
        ],
    },
    "jellyfin": {
        "icon": "☺", "title": "Usuarios de Jellyfin", "desc": "Cuentas e invitaciones de Jellyfin a través de jfa-go.",
        "fields": [
            f("jfa_url", "URL de jfa-go"),
            f("jfa_user", "Usuario de jfa-go", "secret"),
            f("jfa_pass", "Contraseña de jfa-go", "secret"),
            f("jellyfin_url", "URL de Jellyfin"),
            f("public_url", "Web pública de jfa-go", help="Para los enlaces de invitación"),
            f("db", "Ruta a jellyfin.db", help="Opcional: fechas de alta (necesita sqlite3)"),
        ],
    },
}


def secret_keys(module: str) -> set:
    return {x["key"] for x in CATALOG[module]["fields"] if x["type"] == "secret"}
