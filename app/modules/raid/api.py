import asyncio
import time

from fastapi import APIRouter, Depends

from ... import auth
from ...alerts import Alerts
from .raid import parse_raid, raid_command


class RaidMonitor:
    """Lee el estado del RAID (con caché) y avisa de los cambios cada 5 min."""

    def __init__(self, ssh, opts: dict):
        self.ssh, self.opts = ssh, opts
        self.alerts = Alerts()
        self._cache: tuple[float, dict] | None = None
        self._lock = asyncio.Lock()

    async def raid(self, max_age: float = 60) -> dict:
        async with self._lock:
            if self._cache and time.time() - self._cache[0] < max_age:
                return self._cache[1]
            r = parse_raid(await self.ssh.run(raid_command(self.opts), timeout=60), self.opts["device"])
            self._cache = (time.time(), r)
            return r

    async def tick(self, n, now):
        if n % 10:
            return []
        return [(f"RAID: {m}", "/#status") for m in self.alerts.raid(await self.raid(max_age=0))]


def setup(ctx) -> APIRouter:
    raid = ctx.raid = RaidMonitor(ctx.ssh, ctx.cfg.mod("raid"))
    ctx.hooks.append(raid)
    ctx.info["raid"] = {"device": ctx.cfg.mod("raid")["device"]}
    r = APIRouter(dependencies=[Depends(auth.require_auth)])

    @r.get("/api/raid")
    async def get_raid():
        return await raid.raid(max_age=60)

    return r
