"""Comprueba si un módulo tiene lo que necesita, con los valores propuestos (antes de guardarlos)."""
import shlex

import httpx

from .backup import backup_env
from .ssh import SSHError

# chk <id> <nivel> <comando>: imprime PPCHK|id|1|nivel| si va bien, PPCHK|id|0|nivel|última línea si no
PRELUDE = r"""chk() { id=$1; lvl=$2; shift 2
  if out=$(sh -c "$1" 2>&1 </dev/null); then echo "PPCHK|$id|1|$lvl|"
  else echo "PPCHK|$id|0|$lvl|$(printf '%s' "$out" | tail -1 | cut -c1-200)"; fi; }
"""


def _chk(cid: str, level: str, cmd: str) -> str:
    return f"chk {cid} {level} {shlex.quote(cmd)}\n"


def script_for(name: str, v: dict) -> tuple[str, dict]:
    """Script de comprobación (para el host) y etiqueta de cada comprobación."""
    if name == "terminal":
        return PRELUDE + _chk("tmux", "warn", "command -v tmux"), {"tmux": "tmux instalado (para el modo tmux)"}
    if name == "claude":
        home = shlex.quote(v["home"]) if v.get("home") else '"$HOME"'
        cwd = shlex.quote(v["cwd"]) if v.get("cwd") else home
        if v.get("bin"):
            bin_ = shlex.quote(v["bin"])
        elif v.get("home"):
            bin_ = shlex.quote(f"{v['home']}/.local/bin/claude")
        else:
            bin_ = '"$HOME/.local/bin/claude"'
        s = (PRELUDE + _chk("bin", "error", f"test -x {bin_} || {{ echo no está {bin_}; exit 1; }}; "
                                            f"HOME={home} {bin_} --version")
             + _chk("cwd", "error", f"test -d {cwd} || {{ echo no existe {cwd}; exit 1; }}"))
        return s, {"bin": "claude instalado y funcionando", "cwd": "La carpeta de trabajo existe"}
    if name == "backups":
        try:
            e = backup_env(v)
        except ValueError as ex:
            return PRELUDE + _chk("dest", "error", f"echo {shlex.quote(str(ex))}; exit 1"), {"dest": "Destino válido"}
        ssh = f"ssh {e['SSH_OPTS']} {shlex.quote(e['DEST_HOST'])}"
        s = (PRELUDE + _chk("rsync", "error", "command -v rsync")
             + _chk("source", "error", f"test -d {shlex.quote(e['SRC'])} || {{ echo no existe {e['SRC']}; exit 1; }}")
             + _chk("dest", "error", f"{ssh} true")
             + _chk("remote_rsync", "error", f"{ssh} command -v rsync"))
        return s, {"rsync": "rsync instalado", "source": "La carpeta a copiar existe",
                   "dest": "Entra por SSH en el destino", "remote_rsync": "rsync instalado en el destino"}
    if name == "raid":
        dev = shlex.quote(v["device"])
        body = (PRELUDE + _chk("device", "error", f"test -e {dev} || {{ echo no existe {dev}; exit 1; }}")
                + _chk("mdadm", "warn", "command -v mdadm") + _chk("smartctl", "warn", "command -v smartctl"))
        labels = {"device": "El dispositivo existe", "mdadm": "mdadm instalado",
                  "smartctl": "smartctl instalado (para ver la salud de los discos)"}
        if v.get("ssh"):
            ssh = " ".join(x for x in ["ssh -o ConnectTimeout=5 -o BatchMode=yes", v.get("ssh_options") or "",
                                       shlex.quote(v["ssh"]), "sh -s"] if x)
            return f"{ssh} <<'PP_EOF'\n{body}PP_EOF\n", labels
        return body, labels
    if name == "jellyfin" and v.get("db"):
        db = shlex.quote(v["db"])
        return (PRELUDE + _chk("db", "warn", f"test -f {db} || {{ echo no existe {db}; exit 1; }}")
                + _chk("sqlite3", "warn", "command -v sqlite3")), {"db": "La base de datos de Jellyfin existe",
                                                                    "sqlite3": "sqlite3 instalado"}
    return "", {}


def parse_checks(out: str, labels: dict) -> list[dict]:
    seen = {}
    for line in out.splitlines():
        p = line.split("|", 4)
        if len(p) == 5 and p[0] == "PPCHK":
            seen[p[1]] = {"ok": p[2] == "1", "level": p[3], "detail": p[4].strip()}
    return [{"label": label, **seen.get(cid, {"ok": False, "level": "error", "detail": "sin respuesta"})}
            for cid, label in labels.items()]


async def _http_checks(v: dict, http: httpx.AsyncClient) -> list[dict]:
    out = []
    try:
        r = await http.get(f"{v['jfa_url'].rstrip('/')}/token/login", auth=(v.get("jfa_user") or "",
                                                                           v.get("jfa_pass") or ""))
        ok = r.status_code == 200
        detail = "" if ok else ("usuario o contraseña incorrectos" if r.status_code == 401 else f"HTTP {r.status_code}")
    except httpx.HTTPError as e:
        ok, detail = False, f"no responde: {e}"
    out.append({"label": "jfa-go responde y el usuario es correcto", "ok": ok, "level": "error", "detail": detail})
    try:
        r = await http.get(f"{v['jellyfin_url'].rstrip('/')}/System/Info/Public")
        ok, detail = r.status_code == 200, "" if r.status_code == 200 else f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        ok, detail = False, f"no responde: {e}"
    out.append({"label": "Jellyfin responde", "ok": ok, "level": "error", "detail": detail})
    return out


async def check_module(name: str, values: dict, ssh, http: httpx.AsyncClient | None = None) -> list[dict]:
    results = []
    if name == "jellyfin":
        async with (http or httpx.AsyncClient(timeout=8)) as h:
            results += await _http_checks(values, h)
    script, labels = script_for(name, values)
    if script:
        try:
            out = await ssh.run(script, timeout=40)
        except SSHError as e:
            return results + [{"label": "Conexión con el servidor", "ok": False, "level": "error", "detail": str(e)}]
        results += parse_checks(out, labels)
    return results
