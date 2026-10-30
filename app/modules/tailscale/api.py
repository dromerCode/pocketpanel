from fastapi import APIRouter, Depends

from ... import auth
from ...core import Shared
from .tailscale import SCRIPT, parse_status


def setup(ctx) -> APIRouter:
    async def read():
        return parse_status(await ctx.ssh.run(SCRIPT, timeout=15))
    status = Shared(read, ttl=15)
    r = APIRouter(dependencies=[Depends(auth.require_auth)])

    @r.get("/api/tailscale")
    async def tailscale():
        return await status.get()

    return r
