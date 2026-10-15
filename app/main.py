import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, modules
from .config import Config, settings
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


def create_app(cfg: Config) -> FastAPI:
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
