import re
import time
from pathlib import Path

MAX_BYTES = 25 * 1024 * 1024
KEEP_SECONDS = 7 * 86400


def safe_name(name: str) -> str:
    base = Path(name or "archivo").name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "archivo"
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{base[-80:]}"


def clean_old(folder: str, now: float | None = None) -> int:
    now = now or time.time()
    n = 0
    for p in Path(folder).glob("*"):
        if p.is_file() and now - p.stat().st_mtime > KEEP_SECONDS:
            p.unlink()
            n += 1
    return n
