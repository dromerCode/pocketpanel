"""Sugerencias para rellenar el formulario de un módulo: lo que se puede averiguar mirando el servidor.

Cada módulo que quiera tiene un suggest.py con `async def suggest(env) -> dict`, que devuelve
{campo: {"value": valor, "why": "de dónde sale"}} solo con lo que ha encontrado. `env` le da lo común: los
contenedores de Docker (con sus puertos publicados y sus carpetas montadas) y una forma de ejecutar en el host.
La interfaz rellena con eso los campos al abrir el formulario y enseña el porqué debajo de cada uno.

Nada de esto escribe ni cambia nada: solo mira. Si algo falla (sin Docker, sin SSH…), esa parte no sugiere."""
import asyncio
import logging
import posixpath
import shlex

from . import modules
from .ssh import SSHError

log = logging.getLogger("pocketpanel.suggest")
TIMEOUT = 20  # s para todo lo de un módulo


class Container:
    def __init__(self, c: dict):
        self.name = (c.get("Names") or ["/?"])[0].lstrip("/")
        self.image = c.get("Image", "")
        self.running = c.get("State") == "running"
        self.network = (c.get("HostConfig") or {}).get("NetworkMode", "")
        self.labels = c.get("Labels") or {}
        self.ports = {}  # puerto de dentro (tcp) → el publicado en el host
        for p in c.get("Ports") or []:
            if p.get("Type") == "tcp" and p.get("PublicPort"):
                self.ports.setdefault(p["PrivatePort"], p["PublicPort"])
        # carpeta de dentro → la del host (solo las bind mounts: los volúmenes de Docker no se tocan a mano)
        self.mounts = {m["Destination"]: m["Source"] for m in c.get("Mounts") or []
                       if m.get("Type") == "bind" and m.get("Source") and m.get("Destination")}

    def is_(self, *words: str) -> bool:
        """¿Es alguno de estos? Por el nombre del contenedor o el de la imagen (sin registro ni etiqueta)."""
        repo = self.image.rsplit("/", 1)[-1].split(":", 1)[0].split("@", 1)[0].lower()
        name = self.name.lower()
        return any(w in name or w in repo for w in words)

    def url(self, port: int) -> str | None:
        """Cómo llega el panel (que va con red del host) a este puerto de dentro del contenedor."""
        if self.network == "host":
            return f"http://127.0.0.1:{port}"
        if port in self.ports:
            return f"http://127.0.0.1:{self.ports[port]}"
        return None

    def where(self, port: int) -> str:
        pub = port if self.network == "host" else self.ports.get(port)
        return f"contenedor {self.name}, puerto {pub}"


class Env:
    def __init__(self, ssh, docker):
        self.ssh, self.docker = ssh, docker
        self._containers = None

    async def containers(self) -> list[Container]:
        if self._containers is None:
            try:
                self._containers = [Container(c) for c in await self.docker.containers()] if self.docker else []
            except Exception as e:  # noqa: BLE001 — sin Docker no hay nada que sugerir de ahí
                log.info("sin contenedores para sugerir: %s", e)
                self._containers = []
        return self._containers

    async def find(self, *words: str) -> Container | None:
        """El contenedor que es alguno de estos; si hay varios, mejor uno en marcha."""
        found = [c for c in await self.containers() if c.is_(*words)]
        return next((c for c in found if c.running), found[0] if found else None)

    async def sh(self, script: str, timeout: float = 15) -> str:
        """Ejecuta en el host; "" si no se puede."""
        try:
            return await self.ssh.run(script, timeout=timeout)
        except SSHError as e:
            log.info("sin SSH para sugerir: %s", e)
            return ""

    async def read(self, path: str, limit: int = 65536) -> str:
        return await self.sh(f"head -c {limit} {shlex.quote(path)} 2>/dev/null; true")


def app_root(c: Container) -> str | None:
    """La carpeta donde este contenedor guarda lo suyo, si sigue la costumbre <raíz>/<app>/…: la raíz.
    /srv/appdata/qbittorrent-ssd/config → /srv/appdata, para el contenedor `qbittorrent`."""
    name = c.name.lower()
    # Solo /config y /data, la costumbre de las imágenes de apps (linuxserver, hotio…): lo demás suelen ser
    # descargas, medios o webs, que no son «la carpeta de la app»
    for _, src in sorted((m for m in c.mounts.items() if m[0] in ("/config", "/data")), key=lambda m: m[0] != "/config"):
        parts = src.split("/")
        for i, part in enumerate(parts[1:], 1):
            p = part.lower()
            if p and (p.startswith(name) or name.startswith(p)) and len(p) >= 3 and i > 1:
                return "/".join(parts[:i]) or "/"
    return None


def common_dir(paths: list[str]) -> str:
    return posixpath.commonpath(paths) if paths else ""


async def suggest_module(name: str, ssh, docker) -> dict:
    """Las sugerencias de un módulo ({} si no tiene o no encuentra nada)."""
    mod = modules.suggester(name)
    if not mod:
        return {}
    try:
        out = await asyncio.wait_for(mod.suggest(Env(ssh, docker)), TIMEOUT)
    except Exception as e:  # noqa: BLE001 — sugerir es una ayuda: si falla, el formulario sale como siempre
        log.warning("sugerencias de %s: %s", name, e)
        return {}
    return {k: v for k, v in (out or {}).items() if v and v.get("value") not in (None, "", [])}
