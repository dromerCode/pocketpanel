"""Cómo ha organizado el usuario los widgets de Estado (orden, ancho y ocultos), en data/layout.json.

Se guarda en el servidor y no en el navegador para que el móvil y el PC vean lo mismo. El ancho son columnas de una
rejilla de 4 (1 = un cuarto, 4 = todo el ancho); en el móvil 1 es media pantalla y lo demás pantalla entera.

Lo guardado con la rejilla de 12 columnas de antes iba en "status"; ahora va en "widgets", y al leerlo se pasa a 4.
Con otra clave, una pestaña abierta de antes de actualizar no lee anchos de 4 como si fueran de 12: no encuentra
nada y enseña lo de por defecto hasta que se recarga."""
import json
import os
import re
from pathlib import Path

FILE = "layout.json"
SIZES = (1, 2, 3, 4)
OLD_SIZES = {3: 1, 4: 1, 6: 2, 8: 3, 12: 4}  # de 12 columnas a 4
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_ITEMS = 100


class LayoutError(ValueError):
    pass


def load_layout(data_dir: str) -> dict:
    try:
        data = json.loads((Path(data_dir) / FILE).read_text())
    except (OSError, ValueError):
        return {"widgets": []}
    try:
        items = data.get("widgets")
        if items is None and isinstance(data.get("status"), list):
            items = [{**it, "size": OLD_SIZES.get(it.get("size"), 2)} if isinstance(it, dict) else it
                     for it in data["status"]]
        return {"widgets": clean(items)}
    except (LayoutError, AttributeError):
        return {"widgets": []}


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


def save_layout(data_dir: str, widgets) -> dict:
    data = {"widgets": clean(widgets)}
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    tmp = Path(data_dir) / f".{FILE}.tmp"
    tmp.write_text(json.dumps(data))
    os.replace(tmp, Path(data_dir) / FILE)
    return data
