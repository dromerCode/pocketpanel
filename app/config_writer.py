"""Cambia config.yml desde la app conservando comentarios y orden. Valida antes de escribir."""
import io
import tempfile
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .catalog import GENERAL
from .config import MODULE_DEFAULTS, ConfigError, load_config


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def apply_changes(path: str, env, *, general: dict | None = None, module: str | None = None,
                  enabled: bool | None = None, values: dict | None = None, modules: dict | None = None) -> None:
    """Un módulo (module/enabled/values) o varios de golpe (modules={nombre: {enabled, values}})."""
    y = _yaml()
    p = Path(path)
    data = y.load(p.read_text()) if p.exists() and p.read_text().strip() else None
    if data is None:
        data = CommentedMap()
    if general:
        allowed = {x["key"] for x in GENERAL}
        for k, v in general.items():
            if k not in allowed:
                raise ConfigError(f"{k}: no se puede cambiar desde aquí")
            data[k] = v
    changes = dict(modules or {})
    if module is not None:
        changes[module] = {"enabled": enabled, "values": values}
    for module, ch in changes.items():
        enabled, values = (ch or {}).get("enabled"), (ch or {}).get("values")
        if module not in MODULE_DEFAULTS:
            raise ConfigError(f"modules.{module}: módulo desconocido")
        mods = data.setdefault("modules", CommentedMap())
        if mods is None:
            mods = data["modules"] = CommentedMap()
        m = mods.setdefault(module, CommentedMap())
        if m is None:
            m = mods[module] = CommentedMap()
        if enabled is not None:
            m["enabled"] = enabled
        for k, v in (values or {}).items():
            if k not in MODULE_DEFAULTS[module] or k == "enabled":
                raise ConfigError(f"modules.{module}.{k}: opción desconocida")
            m[k] = v
    buf = io.StringIO()
    y.dump(data, buf)
    text = buf.getvalue()
    with tempfile.NamedTemporaryFile("w", suffix=".yml") as tmp:
        tmp.write(text)
        tmp.flush()
        load_config(tmp.name, env)  # lanza ConfigError si no vale
    with open(p, "w") as fh:  # in situ: suele ser un bind mount de un fichero
        fh.write(text)
