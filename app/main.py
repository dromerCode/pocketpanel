import asyncio
import logging
import os
import signal
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, modules
from .catalog import CATALOG, GENERAL, secret_keys
from .config import Config, ConfigError, saved_values, settings
from .config_writer import apply_changes
from .core import json_body
from .secrets import load_secrets, save_secrets
from .core import Context
from .docker_api import DockerClient, DockerError
from .history import HistoryDB
from .jfa import JfaError
from .monitor import Monitor
from .push import PushService
from .ssh import SSH, SSHError
from .system import SYSTEM_SCRIPT, parse_system
from .wsutil import until_disconnect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
for noisy in ("httpx", "asyncssh"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

limiter = auth.LoginLimiter()
RANGES = {"1h": (3600, 30), "24h": (86400, 600), "7d": (7 * 86400, 3600)}


def _restart() -> None:
    """Docker (restart: unless-stopped) vuelve a levantar el contenedor con la config nueva."""
    asyncio.get_running_loop().call_later(0.5, os.kill, os.getpid(), signal.SIGTERM)


def create_app(cfg: Config, restart=None) -> FastAPI:
    restart = restart or _restart
    Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
    ctx = Context(cfg=cfg, ssh=SSH(cfg.ssh_host, cfg.ssh_user, cfg.ssh_key, cfg.known_hosts, cfg.ssh_port),
                  docker=DockerClient(cfg.docker_sock), push=PushService(cfg.data_dir, cfg.push_contact))
    ctx.history = HistoryDB(f"{cfg.data_dir}/history.db")
    routers = modules.load(ctx)
    ctx.monitor = Monitor(cfg, ctx.ssh, ctx.docker, ctx.history, ctx.push, hooks=ctx.hooks)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(ctx.monitor.run())
        yield
        task.cancel()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.cfg, app.state.ctx = cfg, ctx
    authed = [Depends(auth.require_auth)]
    cpu_prev = {}

    @app.exception_handler(SSHError)
    @app.exception_handler(DockerError)
    @app.exception_handler(JfaError)
    async def _unavailable(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    def _ip(request: Request) -> str:
        return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host

    @app.post("/api/login")
    async def login(request: Request, response: Response):
        ip = _ip(request)
        if not limiter.allowed(ip):
            raise HTTPException(429, "demasiados intentos, espera unos minutos")
        body = await request.json()
        if not cfg.pin_hash or not auth.verify_pin(str(body.get("pin", "")), cfg.pin_hash):
            limiter.fail(ip)
            raise HTTPException(401, "PIN incorrecto")
        limiter.ok(ip)
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie(auth.COOKIE, auth.make_token(cfg.secret), max_age=auth.TOKEN_MAX_AGE,
                            httponly=True, samesite="strict", secure=https)
        return {"ok": True}

    @app.post("/api/logout")
    async def logout(response: Response):
        response.delete_cookie(auth.COOKIE)
        return {"ok": True}

    @app.get("/api/me", dependencies=authed)
    async def me():
        enabled = [m for m in modules.MODULES if cfg.enabled(m)]
        return {"name": cfg.name, "modules": enabled, **{k: v for k, v in ctx.info.items() if k in enabled}}

    @app.get("/api/system", dependencies=authed)
    async def system():
        out, containers = await asyncio.gather(ctx.ssh.run(SYSTEM_SCRIPT), ctx.docker.containers())
        r, cpu_prev["v"] = parse_system(out, cpu_prev.get("v"), cfg.disks)
        up = sum(1 for c in containers if c["State"] == "running")
        r["containers"] = {"up": up, "down": len(containers) - up}
        return r

    @app.get("/api/containers", dependencies=authed)
    async def containers():
        from .services import build_services
        cs = await ctx.docker.containers()
        stats = await ctx.docker.stats([c["Id"] for c in cs if c["State"] == "running"])
        out = build_services(cs, stats, cfg.services)
        u = ctx.updater
        for svc in out:
            svc["update"] = bool(u) and u.results.get(svc["name"], {}).get("status") == "update"
            job = u.jobs.get(svc["name"]) if u else None
            svc["updating"] = bool(job and job.status == "running")
        return out

    @app.post("/api/containers/{name}/{verb}", dependencies=authed)
    async def container_action(name: str, verb: str):
        if verb in ("stop", "restart"):
            ctx.monitor.alerts.user_stopped(name, time.time())
        await ctx.docker.action(name, verb)
        return {"ok": True}

    @app.get("/api/history", dependencies=authed)
    async def get_history(range: str = "1h"):
        span, bucket = RANGES.get(range, RANGES["1h"])
        return ctx.history.query(since=int(time.time()) - span, bucket=bucket)

    @app.get("/api/push/key", dependencies=authed)
    async def push_key():
        return {"key": ctx.push.public_key()}

    @app.post("/api/push/subscribe", dependencies=authed)
    async def push_subscribe(request: Request):
        try:
            ctx.push.subscribe(await request.json())
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/push/unsubscribe", dependencies=authed)
    async def push_unsubscribe(request: Request):
        ctx.push.unsubscribe((await request.json()).get("endpoint", ""))
        return {"ok": True}

    @app.post("/api/push/test", dependencies=authed)
    async def push_test():
        return {"sent": await ctx.push.send(cfg.name, "Así se verán los avisos 👍", "/#status")}

    # ---------- Tienda de módulos ----------

    def _module_view(name: str) -> dict:
        values = saved_values(cfg.config_path, name)
        secrets = load_secrets(cfg.data_dir).get(name, {})
        for k in secret_keys(name):
            values[k] = {"set": bool(secrets.get(k))}
        return {"name": name, **CATALOG[name], "enabled": cfg.enabled(name), "values": values}

    @app.get("/api/modules", dependencies=authed)
    async def list_modules():
        general = {f["key"]: getattr(cfg, f["key"]) for f in GENERAL}
        return {"general": {"fields": GENERAL, "values": general},
                "modules": [_module_view(m) for m in modules.MODULES]}

    def _save(**kw) -> dict:
        why = ctx.busy()
        if why:
            raise HTTPException(409, f"ahora no: {why}; prueba en un rato")
        try:
            apply_changes(cfg.config_path, {"PANEL_DATA": cfg.data_dir}, **kw)
        except ConfigError as e:
            raise HTTPException(400, str(e))
        restart()
        return {"restart": True}

    @app.put("/api/modules/{name}", dependencies=authed)
    async def save_module(name: str, request: Request):
        if name not in CATALOG:
            raise HTTPException(404, "módulo desconocido")
        b = await json_body(request)
        values = b.get("values") or {}
        if not isinstance(values, dict):
            raise HTTPException(400, "values no válido")
        secret = {k: str(values.pop(k) or "") for k in list(values) if k in secret_keys(name)}
        enabled = b.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            raise HTTPException(400, "enabled tiene que ser true o false")
        why = ctx.busy()
        if why:
            raise HTTPException(409, f"ahora no: {why}; prueba en un rato")
        if secret:
            save_secrets(cfg.data_dir, name, secret)
        return _save(module=name, enabled=enabled, values=values)

    @app.put("/api/settings", dependencies=authed)
    async def save_settings(request: Request):
        b = await json_body(request)
        return _save(general=b.get("values") or {})

    @app.websocket("/ws/logs/{name}")
    async def ws_logs(ws: WebSocket, name: str):
        if not await auth.ws_authed(ws):
            return
        await ws.accept()

        async def pump():
            try:
                async for chunk in ctx.docker.logs(name):
                    await ws.send_text(chunk)
            except DockerError as e:
                await ws.send_text(f"\n[error] {e}\n")

        tasks = [asyncio.create_task(pump()), asyncio.create_task(until_disconnect(ws))]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in tasks:
            t.cancel()

    for r in routers:
        app.include_router(r)
    app.mount("/", StaticFiles(directory=cfg.web_dir, html=True, check_dir=False), name="web")
    return app


app = create_app(settings)
