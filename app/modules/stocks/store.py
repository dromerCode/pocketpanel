"""Los datos de la cartera: los mismos JSON que usaba el portfolio de antes, en data/stocks/.

holdings.json (posiciones, ventas y efectivo), watchlist.json, <ticker>_tracking.json (opcional: objetivo y stop
manual de un valor) y alerts.json (el último veredicto avisado de cada uno)."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, data_dir: str):
        self.dir = Path(data_dir) / "stocks"

    def read(self, name: str, default=None):
        try:
            return json.loads((self.dir / name).read_text())
        except (OSError, ValueError):
            return default

    def write(self, name: str, data) -> None:
        """Escribe en un temporal y lo cambia de golpe: un corte a medias no deja el JSON roto."""
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f".{name}.tmp"
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        os.replace(tmp, self.dir / name)

    def holdings(self) -> dict:
        h = self.read("holdings.json", None) or {}
        h.setdefault("holdings", [])
        h.setdefault("sold", [])
        h.setdefault("cash_eur", 0)
        return h

    def watchlist(self) -> dict:
        w = self.read("watchlist.json", None) or {}
        w.setdefault("watchlist", [])
        w.setdefault("removed", [])
        return w

    def tracking(self, ticker: str) -> dict | None:
        return self.read(f"{ticker.lower()}_tracking.json")
