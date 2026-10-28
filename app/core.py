import asyncio
import re
import time
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class Shared:
    """El resultado de `fn` compartido durante `ttl` segundos: con varias pantallas abiertas se calcula una vez."""

    def __init__(self, fn, ttl: float = 4):
        self.fn, self.ttl = fn, ttl
        self._lock = asyncio.Lock()
        self._value, self._at = None, -ttl

    async def get(self):
        async with self._lock:
            if time.monotonic() - self._at >= self.ttl:
                self._value = await self.fn()
                self._at = time.monotonic()
            return self._value

    def invalidate(self) -> None:
        self._at = -self.ttl


class UnavailableError(Exception):
    """Un servicio del que depende un módulo no responde: la API contesta 503 con este mensaje."""


@dataclass
class Context:
    """Lo que comparten el núcleo y los módulos.

    Cada módulo deja aquí lo que otros pueden usar (ctx.backup, ctx.updater, ctx.raid, ctx.claude…). Leer algo
    que no ha dejado nadie da None: así un módulo sabe si otro está apagado sin importarlo."""
    cfg: object
    ssh: object
    docker: object
    push: object
    history: object = None
    monitor: object = None
    deps: object = None                               # app.deps.Deps
    deps_pending: list = field(default_factory=list)  # módulos activos que aún esperan sus dependencias
    hooks: list = field(default_factory=list)       # objetos con `async tick(n, now)`, ver Monitor
    busy_checks: list = field(default_factory=list)  # funciones -> motivo para no reiniciar ahora, o None
    info: dict = field(default_factory=dict)  # extra de /api/me por módulo
    visible: dict = field(default_factory=dict)  # id(ws) → la app está en primer plano

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return None

    def busy(self) -> str | None:
        """Algo que un reinicio cortaría a medias (para no guardar ajustes mientras tanto)."""
        for check in self.busy_checks:
            if why := check():
                return why
        return None

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.cfg.timezone)


async def json_body(request: Request) -> dict:
    try:
        b = await request.json()
    except ValueError:
        b = None
    if not isinstance(b, dict):
        raise HTTPException(400, "cuerpo no válido")
    return b
