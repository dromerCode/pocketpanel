"""PIN y secreto de las cookies en data/auth.json (0600): así se pueden crear desde el asistente de la app."""
import json
import os
import secrets
from pathlib import Path

from .auth import hash_pin

FILE = "auth.json"


def load_auth(data_dir: str) -> dict:
    try:
        return json.loads((Path(data_dir) / FILE).read_text())
    except (OSError, ValueError):
        return {}


def _save(data_dir: str, data: dict) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    f = Path(data_dir) / FILE
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)
    os.chmod(f, 0o600)


def save_pin(data_dir: str, pin: str) -> str:
    h = hash_pin(pin)
    _save(data_dir, {**load_auth(data_dir), "pin_hash": h})
    return h


def ensure_secret(data_dir: str) -> str:
    a = load_auth(data_dir)
    if not a.get("secret"):
        a["secret"] = secrets.token_urlsafe(32)
        _save(data_dir, a)
    return a["secret"]
