"""Genera /etc/pocketpanel/backup.conf para el modo root de los backups (lo usa install-root.sh).

    python -m app.modules.backups.rootconf conf      → backup.conf
    python -m app.modules.backups.rootconf excludes  → excludes.txt
    python -m app.modules.backups.rootconf key       → ruta de la clave SSH del destino (vacía si no hay)
"""
import shlex
import sys

from .backup import backup_env
from ...config import load_config

ROOT = "/etc/pocketpanel"


def render(opts: dict) -> str:
    e = backup_env({**opts, "ssh_key": ""})
    # ssh se queda con el primer valor de cada opción: las del usuario van delante para que manden
    ssh = [opts["ssh_options"]] if opts.get("ssh_options") else []
    ssh += ["-o BatchMode=yes -o ConnectTimeout=10", f"-o UserKnownHostsFile={ROOT}/known_hosts"]
    if opts.get("ssh_key"):
        ssh.append(f"-i {ROOT}/id_backup")
    conf = {"SRC": e["SRC"], "DEST_HOST": e["DEST_HOST"], "DEST_PATH": e["DEST_PATH"], "KEEP_DAYS": e["KEEP_DAYS"],
            "EXCLUDES_FILE": f"{ROOT}/excludes.txt", "SSH_OPTS": " ".join(ssh)}
    return "# Generado por install-root.sh desde config.yml. No editar a mano.\n" + "".join(
        f"{k}={shlex.quote(v)}\n" for k, v in conf.items())


def main(what: str) -> None:
    cfg = load_config()
    if not cfg.enabled("backups"):
        sys.exit("el módulo backups no está activado en config.yml")
    m = cfg.mod("backups")
    if what == "conf":
        print(render(m), end="")
    elif what == "excludes":
        print("\n".join(m["excludes"]))
    elif what == "key":
        print(m["ssh_key"])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
