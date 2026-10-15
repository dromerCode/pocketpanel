import re
import shlex
from pathlib import Path

import yaml

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def load_actions(path: str) -> list[dict]:
    """Lee actions.yml en cada llamada (se puede editar sin reiniciar). Ignora entradas mal formadas."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = yaml.safe_load(p.read_text()) or []
    except yaml.YAMLError:
        return []
    out, seen = [], set()
    for a in data if isinstance(data, list) else []:
        if not isinstance(a, dict):
            continue
        aid, name, cmd = str(a.get("id", "")), a.get("name"), a.get("cmd")
        if not ID_RE.match(aid) or aid in seen or not name or not cmd:
            continue
        seen.add(aid)
        out.append({"id": aid, "name": str(name), "cmd": str(cmd).strip(), "confirm": bool(a.get("confirm"))})
    return out


def host_prefix(env: dict) -> str:
    """Variables para los comandos en el host: UTF-8 y las de `host_env` de la config."""
    extra = "".join(f" {k}={shlex.quote(v)}" for k, v in env.items())
    return f"export LANG=C.UTF-8{extra}; "


def action_command(cmd: str, env: dict) -> str:
    return f"{host_prefix(env)}( {cmd}\n) 2>&1"
