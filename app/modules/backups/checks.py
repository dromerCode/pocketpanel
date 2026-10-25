import shlex

from ...requirements import PRELUDE, chk
from .backup import backup_env


def script(v: dict) -> tuple[str, dict]:
    try:
        e = backup_env(v)
    except ValueError as ex:
        return PRELUDE + chk("dest", "error", f"echo {shlex.quote(str(ex))}; exit 1"), {"dest": "Destino válido"}
    ssh = f"ssh {e['SSH_OPTS']} {shlex.quote(e['DEST_HOST'])}"
    s = (PRELUDE + chk("rsync", "error", "command -v rsync")
         + chk("source", "error", f"test -d {shlex.quote(e['SRC'])} || {{ echo no existe {e['SRC']}; exit 1; }}")
         + chk("dest", "error", f"{ssh} true")
         + chk("remote_rsync", "error", f"{ssh} command -v rsync"))
    return s, {"rsync": "rsync instalado", "source": "La carpeta a copiar existe",
               "dest": "Entra por SSH en el destino", "remote_rsync": "rsync instalado en el destino"}
