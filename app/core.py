from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request


@dataclass
class Context:
    """Lo que comparten el núcleo y los módulos. Los módulos rellenan lo suyo (backup, updater, raid, claude)."""
    cfg: object
    ssh: object
    docker: object
    push: object
    history: object = None
    monitor: object = None
    hooks: list = field(default_factory=list)
    info: dict = field(default_factory=dict)  # extra de /api/me por módulo
    visible: dict = field(default_factory=dict)  # id(ws) → la app está en primer plano
    backup: object = None
    updater: object = None
    raid: object = None
    claude: object = None

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
