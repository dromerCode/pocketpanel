from fastapi import APIRouter, Depends, HTTPException, Request

from ... import auth
from ...core import json_body
from ...secrets import load_secrets
from .ntfy import Ntfy, NtfyError

FRESH = 10         # s: si otra pantalla acaba de preguntar, se aprovecha lo que trajo
BACKGROUND = 20    # ticks del monitor (30 s) entre vistazos de fondo cuando no hay que avisar: 10 min
PUSH_MAX = 3       # avisos sueltos por vistazo; el resto, en uno solo


class NtfyHook:
    def __init__(self, refresh, every: int):
        self.refresh, self.every = refresh, every

    async def tick(self, n, now):
        if n % self.every == 0:
            await self.refresh(FRESH)
        return []


def setup(ctx) -> APIRouter:
    m = ctx.cfg.mod("ntfy")
    token = load_secrets(ctx.cfg.data_dir).get("ntfy", {}).get("token", "")
    nt = Ntfy(ctx.cfg.data_dir, m["server"], token)

    async def refresh(max_age: float) -> None:
        new = await nt.poll(max_age)
        if not m["notify"]:
            return
        for msg in new[:PUSH_MAX]:
            await ctx.push.send(msg["title"] or msg["topic"], msg["message"][:300] or "(sin texto)", "/#status")
        if len(new) > PUSH_MAX:
            await ctx.push.send("ntfy", f"y {len(new) - PUSH_MAX} mensajes más", "/#status")

    ctx.hooks.append(NtfyHook(refresh, 1 if m["notify"] else BACKGROUND))
    r = APIRouter(prefix="/api/ntfy", dependencies=[Depends(auth.require_auth)])

    @r.get("")
    async def listing():
        await refresh(FRESH)
        return nt.view()

    @r.post("/topics")
    async def subscribe(request: Request):
        try:
            await nt.add(str((await json_body(request)).get("topic") or ""))
        except NtfyError as e:
            raise HTTPException(400, str(e))
        await refresh(0)
        return nt.view()

    @r.delete("/topics/{topic}")
    async def unsubscribe(topic: str):
        await nt.remove(topic)
        return nt.view()

    return r
