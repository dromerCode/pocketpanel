"""Módulos opcionales. Cada uno expone `setup(ctx) -> APIRouter` y se registra solo si está activo en config.yml."""
import importlib

# Orden de carga: los de abajo usan lo que dejan los de arriba en el contexto (backup, updater, raid).
MODULES = ["terminal", "actions", "updates", "claude", "backups", "raid", "sites", "jellyfin"]
LOAD_ORDER = ["raid", "backups", "updates", "terminal", "actions", "claude", "sites", "jellyfin"]


def load(ctx) -> list:
    routers = []
    for name in LOAD_ORDER:
        if ctx.cfg.enabled(name):
            routers.append(importlib.import_module(f"{__name__}.{name}").setup(ctx))
    return routers
