from fastapi import APIRouter, Depends

from .. import auth
from ..sites import SiteMonitor


def setup(ctx) -> APIRouter:
    mon = SiteMonitor(ctx.cfg.mod("sites"))
    ctx.hooks.append(mon)
    r = APIRouter(dependencies=[Depends(auth.require_auth)])

    @r.get("/api/sites")
    async def sites():
        return mon.view()

    @r.post("/api/sites/check")
    async def check_now():
        for body, url in await mon.check_all():
            await ctx.push.send(ctx.cfg.name, body, url)
        return mon.view()

    return r
