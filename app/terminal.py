import asyncio
import json
import shlex

from fastapi import WebSocket, WebSocketDisconnect

from .claude import UUID_RE


# Sin esto, tmux y Claude pintan los acentos como "_" (la sesión SSH no trae locale)
UTF8 = "export LANG=C.UTF-8 LC_ALL=C.UTF-8; "


def term_command(mode: str, session: str | None, home: str, cwd: str, bin: str) -> str:
    if mode == "shell":
        return f"{UTF8}bash -l"
    if mode == "tmux":
        inner = f"HOME={shlex.quote(home)} {shlex.quote(bin)}"
        return f"{UTF8}tmux -u new-session -A -s claude -c {shlex.quote(cwd)} {shlex.quote(inner)}"
    if mode == "resume":
        if not session or not UUID_RE.match(session):
            raise ValueError("id de sesión no válido")
        inner = f"HOME={shlex.quote(home)} {shlex.quote(bin)} --resume {session}"
        return f"{UTF8}tmux -u new-session -A -s r-{session[:8]} -c {shlex.quote(cwd)} {shlex.quote(inner)}"
    raise ValueError("modo no válido")


async def bridge(ws: WebSocket, ssh, cmd: str, cols: int, rows: int) -> None:
    """Binario del cliente → stdin; texto del cliente = control JSON; salida de la PTY → binario."""
    proc = await ssh.process(cmd, term_type="xterm-256color", term_size=(cols, rows), encoding=None)

    async def pump_out():
        try:
            while True:
                data = await proc.stdout.read(65536)
                if not data:
                    break
                await ws.send_bytes(data)
        finally:
            try:
                await ws.close()
            except RuntimeError:
                pass

    out = asyncio.create_task(pump_out())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                proc.stdin.write(msg["bytes"])
            elif msg.get("text"):
                try:
                    ctl = json.loads(msg["text"])
                    c, r = ctl["resize"]
                    proc.change_terminal_size(int(c), int(r))
                except (ValueError, KeyError, TypeError):
                    pass
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        proc.close()
        out.cancel()
