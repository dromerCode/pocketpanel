import shlex

from ...requirements import PRELUDE, chk


def script(v: dict) -> tuple[str, dict]:
    """Que existe cada carpeta de inicio y que el usuario del host puede leerla."""
    s, labels = PRELUDE, {}
    for i, r in enumerate(v.get("roots") or ["~"]):
        r = str(r).strip()
        path = '"$HOME"' + shlex.quote(r[1:]) if r == "~" or r.startswith("~/") else shlex.quote(r)
        s += chk(f"root{i}", "warn", f"test -d {path} -a -r {path} || {{ echo no existe o no se puede leer; exit 1; }}")
        labels[f"root{i}"] = f"Se puede abrir {r}"
    return s, labels
