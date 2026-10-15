"""Configuración: `.env` (cableado con el host y secretos, lo escribe install.sh) + `config.yml` (lo edita el usuario)."""
import copy
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml

from .secrets import load_secrets


def _load_auth(data_dir: str) -> dict:
    import json
    try:
        return json.loads((Path(data_dir) / "auth.json").read_text())
    except (OSError, ValueError):
        return {}


class ConfigError(Exception):
    pass


TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Valores por defecto de cada módulo. Los tres primeros vienen activados.
MODULE_DEFAULTS: dict[str, dict] = {
    "terminal": {"enabled": True},
    "actions": {"enabled": True},
    "updates": {"enabled": True, "check_at": "05:30"},
    "claude": {"enabled": False, "home": "", "cwd": "", "bin": "", "permission_mode": "", "report_at": "09:00", "report_notes": "", "diagnosis": ""},
    "backups": {"enabled": False, "source": "", "dest": "", "ssh_key": "", "ssh_options": "", "at": "04:00", "keep_days": 7,
                "excludes": ["cache/", "Cache/", "logs/", "log/", "*.log", "transcodes/"]},
    "raid": {"enabled": False, "device": "/dev/md0", "ssh": "", "ssh_options": "", "sudo": False},
    "sites": {"enabled": False, "urls": [], "interval": 5, "cert_warn_days": 14},
    "downloads": {"enabled": False, "qbittorrent_url": "", "sonarr_url": "", "radarr_url": "",
                  "notify_finished": True},
    "jellyfin": {"enabled": False, "jfa_url": "http://127.0.0.1:8056", "jellyfin_url": "http://127.0.0.1:8096",
                 "public_url": "", "db": ""},
}
TIME_KEYS = {("updates", "check_at"), ("claude", "report_at"), ("backups", "at")}
REQUIRED = {"backups": ("source", "dest")}
CHOICES = {("claude", "permission_mode"): ("", "default", "acceptEdits", "plan", "auto", "dontAsk", "bypassPermissions")}

TOP_DEFAULTS = {"name": "servidor", "timezone": "Europe/Madrid", "disks": [], "disk_alert_percent": 90,
                "host_env": {}, "push_contact": "mailto:admin@example.com", "services": {}}
TOP_TYPES = {"name": str, "timezone": str, "disks": list, "disk_alert_percent": int, "host_env": dict,
             "push_contact": str, "services": dict}


@dataclass
class Config:
    name: str
    timezone: str
    disks: list
    disk_alert_percent: int
    host_env: dict
    push_contact: str
    services: dict
    modules: dict  # solo los activos, con sus valores por defecto
    pin_hash: str = ""
    secret: str = ""
    setup_code: str = ""
    ssh_host: str = "127.0.0.1"
    ssh_port: int = 22
    ssh_user: str = "root"
    ssh_key: str = "/ssh/id_ed25519"
    known_hosts: str = "/ssh/known_hosts"
    docker_sock: str = "/var/run/docker.sock"
    web_dir: str = ""
    data_dir: str = "/data"
    uploads_dir: str = "/uploads"
    actions_file: str = "/config/actions.yml"
    host_dir: str = ""
    claude_home: str = ""
    claude_cwd: str = ""
    jfa_user: str = ""
    jfa_pass: str = ""
    config_path: str = ""
    extra: dict = field(default_factory=dict)

    def enabled(self, name: str) -> bool:
        return name in self.modules

    def mod(self, name: str) -> dict:
        return self.modules.get(name) or copy.deepcopy(MODULE_DEFAULTS[name])


def _modules(raw) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("modules: tiene que ser un diccionario")
    out = {}
    for name, defaults in MODULE_DEFAULTS.items():
        given = raw.get(name)
        if given is None:
            given = {}
        if not isinstance(given, dict):
            raise ConfigError(f"modules.{name}: tiene que ser un diccionario")
        for k in given:
            if k not in defaults:
                raise ConfigError(f"modules.{name}.{k}: opción desconocida")
        m = {**copy.deepcopy(defaults), **given}
        if not isinstance(m["enabled"], bool):
            raise ConfigError(f"modules.{name}.enabled: tiene que ser true o false")
        if not m["enabled"]:
            continue
        for k, v in m.items():
            d = defaults[k]
            if (name, k) in TIME_KEYS:
                if v is None and (name, k) == ("claude", "report_at"):
                    continue
                if not isinstance(v, str) or not TIME_RE.match(v):
                    raise ConfigError(f"modules.{name}.{k}: hora no válida (formato HH:MM)")
            elif (name, k) in CHOICES and v not in CHOICES[(name, k)]:
                raise ConfigError(f"modules.{name}.{k}: tiene que ser uno de {', '.join(c for c in CHOICES[(name, k)] if c)}")
            elif type(d) is not type(v):
                raise ConfigError(f"modules.{name}.{k}: tipo no válido (se esperaba {type(d).__name__})")
        for k in REQUIRED.get(name, ()):
            if not m[k]:
                raise ConfigError(f"modules.{name}.{k}: obligatorio")
        out[name] = m
    for name in raw:
        if name not in MODULE_DEFAULTS:
            raise ConfigError(f"modules.{name}: módulo desconocido")
    return out


def load_config(path: str | None = None, env: Mapping | None = None) -> Config:
    env = os.environ if env is None else env
    path = path or env.get("PANEL_CONFIG", "/config/config.yml")
    raw = {}
    p = Path(path)
    if p.exists():
        try:
            raw = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"config.yml no es YAML válido: {e}") from e
        if not isinstance(raw, dict):
            raise ConfigError("config.yml: tiene que ser un diccionario")
    top = {}
    for k, d in TOP_DEFAULTS.items():
        v = raw.get(k, d)
        if v is None:
            v = copy.deepcopy(d)
        if not isinstance(v, TOP_TYPES[k]):
            raise ConfigError(f"{k}: tipo no válido (se esperaba {TOP_TYPES[k].__name__})")
        top[k] = v
    unknown = set(raw) - set(TOP_DEFAULTS) - {"modules"}
    if unknown:
        raise ConfigError(f"{sorted(unknown)[0]}: opción desconocida")
    top["host_env"] = {str(k): str(v) for k, v in top["host_env"].items()}
    top["disks"] = [str(d) for d in top["disks"]]

    e = env.get
    root = Path(__file__).resolve().parent.parent
    data_dir = e("PANEL_DATA", "/data")
    jfa = load_secrets(data_dir).get("jellyfin", {})
    stored = _load_auth(data_dir)
    claude_home = e("CLAUDE_HOME", "")
    try:
        ssh_port = int(e("PANEL_SSH_PORT", "22"))
    except ValueError as ex:
        raise ConfigError("PANEL_SSH_PORT: tiene que ser un número") from ex
    return Config(
        **top,
        modules=_modules(raw.get("modules")),
        pin_hash=stored.get("pin_hash") or e("PANEL_PIN_HASH", ""),
        secret=e("PANEL_SECRET", "") or stored.get("secret", ""),
        setup_code=e("PANEL_SETUP_CODE", ""),
        ssh_host=e("PANEL_SSH_HOST", "127.0.0.1"),
        ssh_port=ssh_port,
        ssh_user=e("PANEL_HOST_USER", "root"),
        ssh_key=e("PANEL_SSH_KEY", "/ssh/id_ed25519"),
        known_hosts=e("PANEL_KNOWN_HOSTS", "/ssh/known_hosts"),
        docker_sock=e("PANEL_DOCKER_SOCK", "/var/run/docker.sock"),
        web_dir=e("PANEL_WEB", str(root / "web")),
        data_dir=data_dir,
        uploads_dir=e("PANEL_UPLOADS", "/uploads"),
        actions_file=e("PANEL_ACTIONS", "/config/actions.yml"),
        host_dir=e("PANEL_HOST_DIR", ""),
        claude_home=claude_home,
        claude_cwd=e("CLAUDE_CWD", "") or claude_home,
        jfa_user=jfa.get("jfa_user") or e("PANEL_JFA_USER", ""),
        jfa_pass=jfa.get("jfa_pass") or e("PANEL_JFA_PASS", ""),
        config_path=str(path),
    )


def saved_values(path: str, name: str) -> dict:
    """Opciones de un módulo tal como están en config.yml (aunque esté apagado), con los valores por defecto."""
    try:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        given = ((raw.get("modules") or {}).get(name)) or {}
    except (OSError, yaml.YAMLError, AttributeError):
        given = {}
    out = {k: v for k, v in copy.deepcopy(MODULE_DEFAULTS[name]).items() if k != "enabled"}
    out.update({k: v for k, v in given.items() if k in out} if isinstance(given, dict) else {})
    return out


settings = load_config()
