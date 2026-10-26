"""Cómo ha organizado el usuario los widgets de Estado (orden, ancho y ocultos), en data/layout.json.

Se guarda en el servidor y no en el navegador para que el móvil y el PC vean lo mismo; en el móvil cada ancho se
traduce a media pantalla o pantalla entera."""
import json
import os
import re
from pathlib import Path

FILE = "layout.json"
SIZES = (3, 4, 6, 8, 12)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_ITEMS = 100


class LayoutError(ValueError):
    pass


def load_layout(data_dir: str) -> dict:
    try:
        data = json.loads((Path(data_dir) / FILE).read_text())
    except (OSError, ValueError):
        return {"status": []}
    try:
        return {"status": clean(data.get("status"))}
    except LayoutError:
        return {"status": []}


def clean(items) -> list[dict]:
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise LayoutError("status tiene que ser una lista de widgets")
    out, seen = [], set()
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("id"), str) or not ID_RE.match(it["id"]):
            raise LayoutError("widget sin id válido")
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        size = it.get("size")
        if size not in SIZES:
            raise LayoutError(f"{it['id']}: el ancho tiene que ser uno de {', '.join(map(str, SIZES))}")
        out.append({"id": it["id"], "size": size, "hidden": bool(it.get("hidden"))})
    return out


def save_layout(data_dir: str, status) -> dict:
    data = {"status": clean(status)}
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    tmp = Path(data_dir) / f".{FILE}.tmp"
    tmp.write_text(json.dumps(data))
    os.replace(tmp, Path(data_dir) / FILE)
    return data
