"""Contraseñas guardadas desde la app (data/secrets.json, 0600). Nunca salen por la API."""
import json
import os
from pathlib import Path

FILE = "secrets.json"


def load_secrets(data_dir: str) -> dict:
    try:
        return json.loads((Path(data_dir) / FILE).read_text())
    except (OSError, ValueError):
        return {}


def save_secrets(data_dir: str, module: str, values: dict) -> None:
    """Guarda los valores no vacíos (vacío = dejar el que había)."""
    s = load_secrets(data_dir)
    s.setdefault(module, {}).update({k: v for k, v in values.items() if v})
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    f = Path(data_dir) / FILE
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(s, fh)
    os.chmod(f, 0o600)
