import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, WebSocket, WebSocketDisconnect

from .. import auth
from ..claude import ClaudeManager, SessionStore
from ..monitor import due_daily
from ..report import Report
from ..ssh import RemoteClaude
from ..uploads import MAX_BYTES, clean_old, safe_name
from .terminal import claude_bin

DIAGNOSIS = """Diagnóstico completo del servidor

Comprueba que todo funciona. NO cambies nada sin preguntarme: si algo está roto, explícame qué pasa y propón el arreglo.

Revisa, por este orden:
1. Contenedores: que estén todos en marcha, reinicios recientes (RestartCount), healthchecks y errores en los últimos logs.
2. Que cada servicio web responde: curl a http://127.0.0.1:<puerto> de cada puerto publicado.
3. Discos: espacio, SMART si está disponible y RAID si lo hay.
4. Backups y montajes de red, si los hay.
5. Red: DNS, Tailscale y salida a internet.

Termina con una tabla ✅/⚠️/❌ por apartado y una lista corta de lo que recomiendas arreglar, de más a menos urgente."""


class ClaudeHook:
    def __init__(self, ctx, report, uploads_dir):
        self.ctx, self.report, self.uploads_dir = ctx, report, uploads_dir
        self._task = None

    async def tick(self, n, now):
        from datetime import datetime
        at = self.ctx.cfg.mod("claude")["report_at"]
        if due_daily(datetime.now(self.ctx.tz), at, self.report.state().get("day")) and not (
                self._task and not self._task.done()):
            self._task = asyncio.create_task(self.report.run())
        if n % 120 == 0:
            clean_old(self.uploads_dir)
        return []


def setup(ctx) -> APIRouter:
    cfg, m = ctx.cfg, ctx.cfg.mod("claude")
    Path(cfg.uploads_dir).mkdir(parents=True, exist_ok=True)
    store = SessionStore(cfg.sessions_dir)
    claude = ctx.claude = ClaudeManager(lambda cmd: RemoteClaude.spawn(ctx.ssh, cmd), cfg.claude_home,
                                        cfg.claude_cwd, claude_bin(cfg))
    report = Report(ctx, claude, notes=m["report_notes"])
    ctx.hooks.append(ClaudeHook(ctx, report, cfg.uploads_dir))
    ctx.info["claude"] = {"diagnosis": m["diagnosis"] or DIAGNOSIS, "report": bool(m["report_at"])}

    def finished(session, summary):
        if report.is_report_turn(claude.turn):  # el informe diario se avisa siempre
            asyncio.create_task(report.finished(session, summary))
            return
        if not any(ctx.visible.values()):  # solo si nadie está mirando la app
            asyncio.create_task(ctx.push.send("Claude ha terminado", summary, f"/#claude/{session or ''}"))

    claude.on_finish = finished
    authed = [Depends(auth.require_auth)]
    r = APIRouter()

    @r.get("/api/report", dependencies=authed)
    async def report_state():
        return report.state()

    @r.post("/api/report", dependencies=authed)
    async def report_now():
        if not await report.run():
            raise HTTPException(409, "Claude está ocupado; prueba en un rato")
        return {"started": True}

    @r.post("/api/claude/upload", dependencies=authed)
    async def upload(file: UploadFile):
        name = safe_name(file.filename)
        dest = Path(cfg.uploads_dir) / name
        size = 0
        with dest.open("wb") as f:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    f.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, "máximo 25 MB por archivo")
                f.write(chunk)
        return {"name": file.filename, "path": f"{cfg.host_dir}/uploads/{name}"}

    @r.get("/api/claude/sessions", dependencies=authed)
    async def sessions():
        return store.list()

    @r.get("/api/claude/sessions/{sid}", dependencies=authed)
    async def session(sid: str):
        # Si hay un turno en marcha en esta sesión, sus mensajes llegan por el WS: no los dupliquemos.
        before = claude.started_at if claude.running and claude.session == sid else None
        res = store.read(sid, before=before)
        if res is None:
            raise HTTPException(404, "no existe")
        return res

    @r.websocket("/ws/claude")
    async def ws_claude(ws: WebSocket):
        if not await auth.ws_authed(ws):
            return
        await ws.accept()
        q = claude.subscribe()
        ctx.visible[id(ws)] = True

        async def push():
            while True:
                await ws.send_json(await q.get())

        pusher = asyncio.create_task(push())
        try:
            while True:
                msg = await ws.receive_json()
                if "attach" in msg:
                    # Por la misma cola y sin await de por medio: el orden con el directo queda garantizado
                    q.put_nowait(claude.state())
                    if claude.running and (msg["attach"] is None or msg["attach"] == claude.session):
                        for ev in claude.snapshot():
                            q.put_nowait({**ev, "replay": True})
                elif "send" in msg:
                    try:
                        await claude.send(str(msg["send"]), msg.get("session"))
                    except (RuntimeError, ValueError) as e:
                        await ws.send_json({"t": "error", "msg": str(e), "sid": msg.get("session")})
                elif msg.get("stop"):
                    await claude.stop()
                elif "visible" in msg:
                    ctx.visible[id(ws)] = bool(msg["visible"])
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass
        finally:
            claude.unsubscribe(q)
            ctx.visible.pop(id(ws), None)
            pusher.cancel()

    return r
