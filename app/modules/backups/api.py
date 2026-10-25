import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import auth
from .backup import Backup
from ...core import json_body
from ...monitor import due_daily
from .restore import Restorer


class BackupHook:
    def __init__(self, ctx, backup):
        self.ctx, self.backup = ctx, backup

    async def tick(self, n, now):
        b = self.backup
        if not b.running and due_daily(datetime.now(self.ctx.tz), self.ctx.cfg.mod("backups")["at"],
                                       b.state().get("daily")):
            asyncio.create_task(b.run())
        return []


def setup(ctx) -> APIRouter:
    m = ctx.cfg.mod("backups")
    backup = ctx.backup = Backup(ctx.ssh, m, ctx.cfg.data_dir, ctx.tz, ctx.push)
    restorer = ctx.restorer = Restorer(ctx.ssh, ctx.docker, backup, m, ctx.push)
    ctx.hooks.append(BackupHook(ctx, backup))
    ctx.busy_checks.append(lambda: "hay un backup en marcha" if backup.running else None)
    ctx.busy_checks.append(lambda: "hay una restauración en marcha"
                           if any(j.status == "running" for j in restorer.jobs.values()) else None)
    ctx.info["backups"] = {"source": m["source"], "dest": m["dest"], "at": m["at"], "keep_days": m["keep_days"]}
    r = APIRouter(dependencies=[Depends(auth.require_auth)])

    @r.get("/api/backup")
    async def backup_state():
        return backup.state()

    @r.post("/api/backup")
    async def backup_now():
        if not backup.running:
            asyncio.create_task(backup.run(label="manual"))
        return {"started": True}

    @r.get("/api/restore/snapshots")
    async def restore_snapshots():
        return await restorer.snapshots()

    @r.get("/api/restore/apps/{container}")
    async def restore_apps(container: str):
        return await restorer.apps_for(container)

    @r.post("/api/restore/preview")
    async def restore_preview(request: Request):
        b = await json_body(request)
        try:
            return await restorer.preview(str(b.get("snapshot", "")), str(b.get("app", "")))
        except ValueError as e:
            raise HTTPException(400, str(e))
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    @r.post("/api/restore")
    async def restore_start(request: Request):
        b = await json_body(request)
        try:
            return restorer.start(str(b.get("snapshot", "")), str(b.get("app", ""))).view()
        except ValueError as e:
            raise HTTPException(409, str(e))

    @r.get("/api/restore/job/{app_name}")
    async def restore_job(app_name: str):
        j = restorer.jobs.get(app_name)
        if not j:
            raise HTTPException(404, "no hay restauración de esa carpeta")
        return j.view()

    return r
