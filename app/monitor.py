import asyncio
import logging
import time
from datetime import datetime

from .alerts import Alerts
from .system import SYSTEM_SCRIPT, parse_system

log = logging.getLogger("pocketpanel.monitor")
INTERVAL = 30
HISTORY_DAYS = 7


def due_daily(now: datetime, at: str | None, last_day: str | None) -> bool:
    """¿Toca la tarea diaria programada a las `at` (HH:MM) y aún no se ha hecho hoy?"""
    if not at:
        return False
    h, m = (int(x) for x in at.split(":"))
    return (now.hour, now.minute) >= (h, m) and last_day != now.strftime("%Y-%m-%d")


class Monitor:
    """Cada 30 s: guarda una muestra para las gráficas, busca cosas que avisar por push y da paso a los
    módulos (`hooks`: objetos con `async tick(n, now) -> [(texto, url)]`)."""

    def __init__(self, cfg, ssh, docker, history, push, hooks=None):
        self.cfg, self.ssh, self.docker, self.history, self.push = cfg, ssh, docker, history, push
        self.hooks = list(hooks or [])
        self.alerts = Alerts(cfg.disk_alert_percent)
        self._cpu_prev = None

    async def tick(self, n: int) -> None:
        now = time.time()
        notes: list[tuple[str, str]] = []
        out = await self.ssh.run(SYSTEM_SCRIPT)
        r, self._cpu_prev = parse_system(out, self._cpu_prev, self.cfg.disks)
        mem = round(r["mem"]["used"] * 100 / r["mem"]["total"], 1) if r["mem"] else None
        self.history.add(int(now), r["cpu"], mem, r["temp"])
        notes += [(m, "/#status") for m in self.alerts.disks(r["disks"])]

        cs = await self.docker.containers()
        states = {c["Names"][0].lstrip("/"): c["State"] for c in cs}
        notes += [(m, "/#services/down") for m in self.alerts.containers(states, now)]

        for hook in self.hooks:
            try:
                notes += await hook.tick(n, now) or []
            except Exception as e:  # noqa: BLE001 — un módulo con problemas no debe tapar al resto
                log.warning("%s: %s: %s", type(hook).__name__, type(e).__name__, e)
        if n % 120 == 0:
            self.history.prune(int(now) - HISTORY_DAYS * 86400)

        for body, url in notes:
            log.info("aviso: %s", body)
            await self.push.send(self.cfg.name, body, url)

    async def run(self) -> None:
        n = 0
        while True:
            try:
                await self.tick(n)
            except Exception as e:  # noqa: BLE001 — el monitor no debe morir nunca
                log.warning("monitor: %s: %s", type(e).__name__, e)
            n += 1
            await asyncio.sleep(INTERVAL)
