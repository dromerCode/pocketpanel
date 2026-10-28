from fastapi import APIRouter, Depends, HTTPException, Request

from ... import auth
from ...core import json_body
from ...ssh import SSHError
from .packages import Packages, PackagesError


def setup(ctx) -> APIRouter:
    pk = Packages(ctx.ssh)
    r = APIRouter(prefix="/api/packages", dependencies=[Depends(auth.require_auth)])

    @r.get("")
    async def listing(fresh: bool = False):
        try:
            return await pk.listing(fresh)
        except SSHError as e:
            raise HTTPException(502, str(e))

    @r.post("/run")
    async def run(request: Request):
        try:
            await pk.start(bool((await json_body(request)).get("upgrade")))
        except PackagesError as e:
            raise HTTPException(409, str(e))
        except SSHError as e:
            raise HTTPException(502, str(e))
        return {"started": True}

    @r.get("/job")
    async def job():
        j = await pk.job()
        if j is None:
            raise HTTPException(404, "todavía no se ha actualizado nada desde el panel")
        return j

    return r
