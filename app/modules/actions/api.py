import asyncio

from fastapi import APIRouter, Depends, WebSocket

from ... import auth
from .actions import action_command, load_actions
from ...ssh import SSHError
from ...wsutil import until_disconnect


def setup(ctx) -> APIRouter:
    cfg = ctx.cfg
    r = APIRouter()

    @r.get("/api/actions", dependencies=[Depends(auth.require_auth)])
    async def actions():
        return load_actions(cfg.actions_file)

    @r.websocket("/ws/action/{aid}")
    async def ws_action(ws: WebSocket, aid: str):
        if not await auth.ws_authed(ws):
            return
        await ws.accept()
        act = next((a for a in load_actions(cfg.actions_file) if a["id"] == aid), None)
        if not act:
            await ws.send_json({"error": "acción desconocida"})
            return await ws.close()
        try:
            proc = await ctx.ssh.process(action_command(act["cmd"], cfg.host_env))
        except SSHError as e:
            await ws.send_json({"error": str(e)})
            return await ws.close()

        async def pump():
            while data := await proc.stdout.read(4096):
                await ws.send_text(data)
            res = await proc.wait(check=False)
            await ws.send_json({"exit": res.exit_status})

        tasks = [asyncio.create_task(pump()), asyncio.create_task(until_disconnect(ws))]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in tasks:
            t.cancel()
        proc.close()
        try:
            await ws.close()
        except RuntimeError:
            pass

    return r
