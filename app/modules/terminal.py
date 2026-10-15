import json

from fastapi import APIRouter, WebSocket

from .. import auth
from ..ssh import SSHError
from ..terminal import bridge, term_command


def setup(ctx) -> APIRouter:
    r = APIRouter()
    cfg = ctx.cfg
    ctx.info["terminal"] = {"tmux": cfg.enabled("claude")}

    @r.websocket("/ws/term")
    async def ws_term(ws: WebSocket, mode: str = "shell", session: str | None = None, cols: int = 80, rows: int = 24):
        if not await auth.ws_authed(ws):
            return
        await ws.accept()
        try:
            if mode != "shell" and not cfg.enabled("claude"):
                raise ValueError("modo no válido")
            cmd = term_command(mode, session, cfg.claude_home, cfg.claude_cwd, claude_bin(cfg))
            await bridge(ws, ctx.ssh, cmd, cols, rows)
        except (ValueError, SSHError) as e:
            await ws.send_text(json.dumps({"error": str(e)}))
            await ws.close()

    return r


def claude_bin(cfg) -> str:
    return cfg.mod("claude")["bin"] or f"{cfg.claude_home}/.local/bin/claude"
