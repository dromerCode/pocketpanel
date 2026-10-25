"""Comprueba si un módulo tiene lo que necesita, con los valores propuestos (antes de guardarlos).
Lo que comprueba cada uno está en su app/modules/<nombre>/checks.py; aquí, lo común."""
import shlex

import httpx

from . import modules
from .ssh import SSHError

# chk <id> <nivel> <comando>: imprime PPCHK|id|1|nivel| si va bien, PPCHK|id|0|nivel|última línea si no
PRELUDE = r"""chk() { id=$1; lvl=$2; shift 2
  if out=$(sh -c "$1" 2>&1 </dev/null); then echo "PPCHK|$id|1|$lvl|"
  else echo "PPCHK|$id|0|$lvl|$(printf '%s' "$out" | tail -1 | cut -c1-200)"; fi; }
"""


def chk(cid: str, level: str, cmd: str) -> str:
    """Una comprobación del script: `cmd` tiene que salir con 0. level: error (no funcionará) o warn."""
    return f"chk {cid} {level} {shlex.quote(cmd)}\n"


def script_for(name: str, v: dict) -> tuple[str, dict]:
    """Script de comprobación (para el host) y etiqueta de cada comprobación."""
    mod = modules.checks(name)
    return mod.script(v) if mod and hasattr(mod, "script") else ("", {})


def parse_checks(out: str, labels: dict) -> list[dict]:
    seen = {}
    for line in out.splitlines():
        p = line.split("|", 4)
        if len(p) == 5 and p[0] == "PPCHK":
            seen[p[1]] = {"ok": p[2] == "1", "level": p[3], "detail": p[4].strip()}
    return [{"label": label, **seen.get(cid, {"ok": False, "level": "error", "detail": "sin respuesta"})}
            for cid, label in labels.items()]


async def check_module(name: str, values: dict, ssh, http: httpx.AsyncClient | None = None) -> list[dict]:
    results = []
    mod = modules.checks(name)
    if mod and hasattr(mod, "http_checks"):
        async with (http or httpx.AsyncClient(timeout=8)) as h:
            results += await mod.http_checks(values, h)
    script, labels = script_for(name, values)
    if script:
        try:
            out = await ssh.run(script, timeout=40)
        except SSHError as e:
            return results + [{"label": "Conexión con el servidor", "ok": False, "level": "error", "detail": str(e)}]
        results += parse_checks(out, labels)
    return results
