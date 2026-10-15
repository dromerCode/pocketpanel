import asyncio
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from .. import auth
from ..core import json_body
from ..jellyfin_meta import meta_command, parse_meta
from ..jfa import Jfa
from ..ssh import SSHError


def setup(ctx) -> APIRouter:
    m = ctx.cfg.mod("jellyfin")
    jfa = Jfa(m["jfa_url"], ctx.cfg.jfa_user, ctx.cfg.jfa_pass, m["public_url"])
    ctx.info["jellyfin"] = {"public_url": m["public_url"]}
    http = httpx.AsyncClient(timeout=10)
    cache: dict = {}
    r = APIRouter(dependencies=[Depends(auth.require_auth)])

    async def jellyfin_meta() -> dict:
        """Fecha de alta y si tiene foto, sacado de la BD de Jellyfin (solo lectura). Caché de 10 min."""
        if not m["db"]:
            return {}
        if cache and time.time() - cache["at"] < 600:
            return cache["meta"]
        try:
            meta = parse_meta(await ctx.ssh.run(meta_command(m["db"]), timeout=20))
        except SSHError:
            meta = cache.get("meta", {})
        cache.update(at=time.time(), meta=meta)
        return meta

    @r.get("/api/jfa/users")
    async def jfa_users():
        us, meta = await asyncio.gather(jfa.users(), jellyfin_meta())
        for u in us:
            mm = meta.get(u["id"], {})
            u["since"], u["since_approx"], u["image"] = mm.get("since"), mm.get("approx", True), mm.get("image", False)
        return us

    @r.get("/api/jfa/avatar/{uid}")
    async def jfa_avatar(uid: str):
        if not (len(uid) == 32 and all(c in "0123456789abcdef" for c in uid)):
            raise HTTPException(400, "id no válido")
        try:
            res = await http.get(f"{m['jellyfin_url']}/UserImage", params={"userId": uid, "maxWidth": 96, "quality": 85})
        except httpx.HTTPError:
            raise HTTPException(503, "Jellyfin no responde")
        if res.status_code != 200:
            raise HTTPException(404, "sin foto")
        return Response(res.content, media_type=res.headers.get("content-type", "image/jpeg"),
                        headers={"Cache-Control": "private, max-age=86400"})

    @r.post("/api/jfa/users")
    async def jfa_create_user(request: Request):
        b = await json_body(request)
        return await jfa.create_user(str(b.get("username", "")), str(b.get("password", "")),
                                     str(b.get("email", "")), int(b.get("months") or 0))

    @r.post("/api/jfa/users/{uid}/{action}")
    async def jfa_user_action(uid: str, action: str, request: Request):
        b = await json_body(request) if action == "extend" else {}
        if action == "extend":
            await jfa.extend([uid], months=int(b.get("months") or 0), days=int(b.get("days") or 0),
                             timestamp=b.get("timestamp"))
        elif action == "no-expiry":
            await jfa.remove_expiry(uid)
        elif action in ("enable", "disable"):
            await jfa.enable([uid], action == "enable")
        elif action == "delete":
            await jfa.delete([uid])
        else:
            raise HTTPException(404, "acción desconocida")
        return {"ok": True}

    @r.get("/api/jfa/invites")
    async def jfa_invites():
        return await jfa.invites()

    @r.post("/api/jfa/invites")
    async def jfa_create_invite(request: Request):
        b = await json_body(request)
        return await jfa.create_invite(str(b.get("label", "")), int(b.get("uses", 1)),
                                       int(b.get("valid_days", 7)), int(b.get("user_months", 0)))

    @r.delete("/api/jfa/invites/{code}")
    async def jfa_delete_invite(code: str):
        await jfa.delete_invite(code)
        return {"ok": True}

    return r
