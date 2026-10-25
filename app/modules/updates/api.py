import asyncio
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ... import auth
from ...monitor import due_daily
from .updater import Updater


class UpdatesHook:
    def __init__(self, ctx, updater):
        self.ctx, self.updater = ctx, updater

    async def tick(self, n, now):
        u = self.updater
        if u.checking:
            return []
        tz = self.ctx.tz
        checked_day = datetime.fromtimestamp(u.checked_at, tz).strftime("%Y-%m-%d") if u.checked_at else None
        if (u.checked_at is None and n >= 2) or due_daily(datetime.now(tz), self.ctx.cfg.mod("updates")["check_at"],
                                                          checked_day):
            asyncio.create_task(u.check())
        return []


def setup(ctx) -> APIRouter:
    updater = ctx.updater = Updater(ctx.docker, httpx.AsyncClient(timeout=20, follow_redirects=True),
                                    backup=ctx.backup, push=ctx.push, data_dir=ctx.cfg.data_dir)
    ctx.hooks.append(UpdatesHook(ctx, updater))
    ctx.busy_checks.append(lambda: "hay una actualización en marcha"
                           if any(j.status == "running" for j in updater.jobs.values()) else None)
    r = APIRouter(dependencies=[Depends(auth.require_auth)])

    @r.get("/api/updates")
    async def updates():
        return {"checked_at": updater.checked_at, "checking": updater.checking, "results": updater.results,
                "jobs": {n: j.status for n, j in updater.jobs.items()}}

    @r.post("/api/updates-all")
    async def update_all():
        try:
            return updater.start_all().view()
        except ValueError as e:
            raise HTTPException(409, str(e))

    @r.post("/api/updates/check")
    async def updates_check():
        if not updater.checking:
            asyncio.create_task(updater.check())
        return {"started": True}

    @r.post("/api/updates/{name}")
    async def update_container(name: str, force: bool = False):
        try:
            return updater.start(name, force=force).view()
        except ValueError as e:
            raise HTTPException(409, str(e))

    @r.get("/api/updates/{name}/job")
    async def update_job(name: str):
        j = updater.jobs.get(name)
        if not j:
            raise HTTPException(404, "no hay actualización para este contenedor")
        return j.view()

    return r
