"""Registro de módulos: cada subcarpeta con un `MODULE` en su __init__.py es un módulo (ver app/module.py).
Solo se importa el api.py de los que están activos en config.yml."""
import dataclasses
import importlib
import pkgutil
from pathlib import Path

from ..module import Module


def _discover() -> dict[str, Module]:
    found = {}
    for info in pkgutil.iter_modules(__path__):
        if not info.ispkg:
            continue
        m = getattr(importlib.import_module(f"{__name__}.{info.name}"), "MODULE", None)
        if not isinstance(m, Module):
            raise RuntimeError(f"app/modules/{info.name}: falta MODULE = Module(...) en su __init__.py")
        found[info.name] = dataclasses.replace(m, name=info.name)
    return dict(sorted(found.items(), key=lambda kv: (kv[1].order, kv[0])))


REGISTRY = _discover()
MODULES = list(REGISTRY)


def load_order() -> list[str]:
    """Los de `after` primero; si no, en el orden de la tienda."""
    out, seen = [], set()

    def visit(name, path=()):
        if name in seen:
            return
        if name in path:
            raise RuntimeError(f"módulos: dependencia circular {' → '.join((*path, name))}")
        for dep in REGISTRY[name].after:
            if dep not in REGISTRY:
                raise RuntimeError(f"módulo {name}: after={dep!r} no existe")
            visit(dep, (*path, name))
        seen.add(name)
        out.append(name)

    for name in REGISTRY:
        visit(name)
    return out


def load(ctx) -> list:
    return [importlib.import_module(f"{__name__}.{name}.api").setup(ctx)
            for name in load_order() if ctx.cfg.enabled(name)]


def checks(name: str):
    """El checks.py del módulo, o None si no necesita comprobar nada."""
    try:
        return importlib.import_module(f"{__name__}.{name}.checks")
    except ModuleNotFoundError as e:
        if e.name != f"{__name__}.{name}.checks":
            raise
        return None


def web_dir(name: str) -> Path | None:
    """La carpeta web/ del módulo (se sirve en /modules/<nombre>/), si tiene interfaz."""
    d = Path(__file__).parent / name / "web"
    return d if (d / "index.js").is_file() else None
