import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import auth
from ...core import Shared, json_body
from ...ssh import SSHError
from .clientes import Clientes, ClientesError


def setup(ctx) -> APIRouter:
    cl = Clientes(ctx.ssh, ctx.cfg.mod("clientes")["script"])
    # Con varias pantallas abiertas (o el widget y la pestaña) se pregunta una vez
    estado = Shared(cl.estado, ttl=8)
    versiones = Shared(cl.versiones, ttl=300)
    r = APIRouter(prefix="/api/clientes", dependencies=[Depends(auth.require_auth)])

    async def call(fn, *a):
        try:
            return await fn(*a)
        except ClientesError as e:
            raise HTTPException(409, str(e))
        except SSHError as e:
            raise HTTPException(502, str(e))

    last = {"at": 0.0, "value": None}

    @r.get("")
    async def status(soft: bool = False):
        # soft: al widget de Estado le vale lo de hace un par de minutos (no entra en la VM cada 30 s)
        if not (soft and last["value"] and time.monotonic() - last["at"] < 120):
            last["value"], last["at"] = await call(estado.get), time.monotonic()
        return last["value"]

    @r.get("/dns")
    async def dns():
        return await call(cl.dns)

    @r.get("/copias")
    async def copias():
        return await call(cl.copias)

    @r.get("/versiones")
    async def get_versiones(fresh: bool = False):
        if fresh:
            versiones.invalidate()
        return await call(versiones.get)

    @r.get("/sucesos")
    async def sucesos():
        return {"events": await call(cl.sucesos)}

    @r.get("/crons")
    async def crons():
        return await call(cl.crons)

    @r.get("/logs")
    async def logs(name: str, lines: int = 200):
        return {"lines": await call(cl.logs, name, lines)}

    @r.get("/job")
    async def job():
        j = await call(cl.job)
        if j is None:
            raise HTTPException(404, "todavía no se ha lanzado nada desde el panel")
        return j

    @r.post("/run")
    async def run(request: Request):
        name = await call(cl.run, await json_body(request))
        estado.invalidate()
        last["at"] = 0.0  # que el widget vea ya que hay algo en marcha
        return {"started": True, "name": name}

    @r.post("/cron")
    async def cron(request: Request):
        return {"result": await call(cl.cron, await json_body(request))}

    return r
