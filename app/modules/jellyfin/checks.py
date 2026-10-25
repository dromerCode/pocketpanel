import shlex

import httpx

from ...requirements import PRELUDE, chk


def script(v: dict) -> tuple[str, dict]:
    if not v.get("db"):
        return "", {}
    db = shlex.quote(v["db"])
    return (PRELUDE + chk("db", "warn", f"test -f {db} || {{ echo no existe {db}; exit 1; }}")
            + chk("sqlite3", "warn", "command -v sqlite3")), {"db": "La base de datos de Jellyfin existe",
                                                               "sqlite3": "sqlite3 instalado"}


async def http_checks(v: dict, http: httpx.AsyncClient) -> list[dict]:
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
