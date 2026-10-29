import asyncio
import hmac
import logging
import os
import re
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
from .core import Shared, json_body
from .authstore import ensure_secret, save_pin
from .secrets import load_secrets, save_secrets
from .core import Context, UnavailableError
from .deps import Deps
from .docker_api import DockerClient, DockerError
from .history import HistoryDB
from .layout import LayoutError, load_layout, save_layout
from .monitor import Monitor
from .push import PushService
from .ssh import SSH, SSHError
from .assets import IMMUTABLE, Assets, GzipJSON
from .processes import ProcessError, Processes
from .system import SystemSampler
from .wsutil import until_disconnect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
# httpx apunta cada petición con la URL entera, y la de Telegram lleva el token del bot (bot<token>/sendMessage)
logging.getLogger("httpx").setLevel(logging.WARNING)
for noisy in ("httpx", "asyncssh"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

limiter = auth.LoginLimiter()
RANGES = {"1h": (3600, 30), "24h": (86400, 600), "7d": (7 * 86400, 3600)}


def _restart() -> None:
    """Docker (restart: unless-stopped) vuelve a levantar el contenedor con la config nueva."""
    asyncio.get_running_loop().call_later(0.5, os.kill, os.getpid(), signal.SIGTERM)


PIN_RE = re.compile(r"^\d{4,12}$")


class Static(StaticFiles):
    """Sin Cache-Control el navegador se queda con la versión vieja horas (caché heurística) tras actualizar el panel:
    así revalida siempre, y si no ha cambiado es un 304 de nada."""

    def file_response(self, *args, **kwargs):
        r = super().file_response(*args, **kwargs)
        r.headers["Cache-Control"] = "no-cache"
        return r


def create_app(cfg: Config, restart=None, deps=None) -> FastAPI:
    restart = restart or _restart
    Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
    if not cfg.secret:
        cfg.secret = ensure_secret(cfg.data_dir)
    ctx = Context(cfg=cfg, ssh=SSH(cfg.ssh_host, cfg.ssh_user, cfg.ssh_key, cfg.known_hosts, cfg.ssh_port),
                  docker=DockerClient(cfg.docker_sock), push=PushService(cfg.data_dir, cfg.push_contact))
    ctx.history = HistoryDB(f"{cfg.data_dir}/history.db")
    ctx.deps = deps or Deps(cfg.data_dir)
    ctx.deps.prune([m for m in modules.MODULES if cfg.enabled(m)])
    routers = modules.load(ctx)
    ctx.sampler = SystemSampler(ctx.ssh, ctx.docker, cfg.disks)
    ctx.monitor = Monitor(cfg, ctx.ssh, ctx.docker, ctx.history, ctx.push, hooks=ctx.hooks, sampler=ctx.sampler)
    loaded = lambda m: cfg.enabled(m) and m not in ctx.deps_pending  # noqa: E731
    installing: dict[str, asyncio.Task] = {}

    async def install_deps(names: list[str]) -> None:
        """Descarga lo que falte y reinicia para cargar los módulos (cuando nada impida reiniciar)."""
        ok = True
        for name in names:
            ok = (await ctx.deps.install(name)).status == "ok" and ok
        if not ok:
            return
        while ctx.busy():
            await asyncio.sleep(10)
        restart()

    def start_install(names: list[str]) -> None:
        names = [n for n in names if not (installing.get(n) and not installing[n].done())]
        if names:
            t = asyncio.create_task(install_deps(names))
            installing.update({n: t for n in names})

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(ctx.monitor.run())
        start_install(ctx.deps_pending)
        yield
        task.cancel()
        for t in installing.values():
            t.cancel()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.cfg, app.state.ctx = cfg, ctx
    authed = [Depends(auth.require_auth)]

    @app.exception_handler(SSHError)
    @app.exception_handler(DockerError)
    @app.exception_handler(UnavailableError)
    async def _unavailable(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    def _ip(request: Request) -> str:
        # Nunca X-Forwarded-For a pelo: cualquiera podría cambiarlo en cada intento y saltarse el límite del PIN.
        # uvicorn (--proxy-headers) ya pone aquí la IP real cuando la petición llega de un proxy de confianza
        # (PANEL_TRUSTED_PROXIES); si no, es la de quien se conecta.
        return request.client.host

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
        https = request.url.scheme == "https"  # con un proxy de confianza, uvicorn ya lo ha puesto a https
        response.set_cookie(auth.COOKIE, auth.make_token(cfg.secret), max_age=auth.TOKEN_MAX_AGE,
                            httponly=True, samesite="strict", secure=https)
        return {"ok": True}

    @app.post("/api/logout")
    async def logout(response: Response):
        response.delete_cookie(auth.COOKIE)
        return {"ok": True}

    @app.get("/api/me", dependencies=authed)
    async def me():
        enabled = [m for m in modules.MODULES if loaded(m)]
        return {"name": cfg.name, "modules": enabled, "ui": [m for m in enabled if modules.web_dir(m)],
                "deps_pending": ctx.deps_pending, **{k: v for k, v in ctx.info.items() if k in enabled}}

    @app.get("/api/system", dependencies=authed)
    async def system():
        r, containers = await ctx.sampler.sample()
        r = dict(r)
        up = sum(1 for c in containers if c["State"] == "running")
        r["containers"] = {"up": up, "down": len(containers) - up}
        return r

    procs = Processes(ctx.ssh, ctx.docker)

    @app.get("/api/processes", dependencies=authed)
    async def processes(sort: str = "cpu", q: str = ""):
        return await procs.sample(sort, q)

    @app.post("/api/processes/{pid}/{sig}", dependencies=authed)
    async def process_signal(pid: int, sig: str):
        try:
            await procs.signal(pid, sig.upper())
        except ProcessError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    async def _services():
        from .services import build_services
        cs = await ctx.docker.containers()
        stats = await ctx.docker.stats([c["Id"] for c in cs if c["State"] == "running"])
        return build_services(cs, stats, cfg.services)
    services_now = Shared(_services)  # una consulta a Docker por contenedor, compartida entre pantallas

    @app.get("/api/containers", dependencies=authed)
    async def containers():
        u = ctx.updater
        out = [dict(svc) for svc in await services_now.get()]
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
        services_now.invalidate()
        return {"ok": True}

    @app.get("/api/history", dependencies=authed)
    async def get_history(range: str = "1h"):
        span, bucket = RANGES.get(range, RANGES["1h"])
        return ctx.history.query(since=int(time.time()) - span, bucket=bucket)

    @app.get("/api/layout", dependencies=authed)
    async def get_layout():
        return load_layout(cfg.data_dir)

    @app.put("/api/layout", dependencies=authed)
    async def put_layout(request: Request):
        try:
            return save_layout(cfg.data_dir, (await json_body(request)).get("widgets"))
        except LayoutError as e:
            raise HTTPException(400, str(e))

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

    # ---------- Asistente de instalación (solo mientras no hay PIN) ----------

    def _setup_code(request: Request, code: str) -> None:
        ip = _ip(request)
        if not limiter.allowed(ip):
            raise HTTPException(429, "demasiados intentos, espera unos minutos")
        norm = lambda c: re.sub(r"[^A-Z0-9]", "", (c or "").upper())  # noqa: E731
        if not cfg.setup_code or not hmac.compare_digest(norm(code), norm(cfg.setup_code)):
            limiter.fail(ip)
            raise HTTPException(403, "código de instalación incorrecto (te lo dio ./install.sh)")

    @app.get("/api/setup")
    async def setup_info(request: Request, code: str | None = None):
        if cfg.pin_hash or code is None:
            return {"needed": not cfg.pin_hash}
        _setup_code(request, code)
        try:
            hostname = (await ctx.ssh.run("hostname", timeout=8)).strip()
        except SSHError:
            hostname = ""
        return {"needed": True, "hostname": hostname, "timezone": cfg.timezone, "name": cfg.name,
                "modules": [_module_view(m) for m in modules.MODULES]}

    @app.post("/api/setup/check/{name}")
    async def setup_check(name: str, request: Request):
        from .requirements import check_module
        b = await json_body(request)
        if cfg.pin_hash:
            raise HTTPException(409, "ya está configurado")
        _setup_code(request, str(b.get("code", "")))
        if name not in CATALOG:
            raise HTTPException(404, "módulo desconocido")
        return await check_module(name, {**saved_values(cfg.config_path, name), **(b.get("values") or {})}, ctx.ssh)

    @app.post("/api/setup")
    async def setup_done(request: Request, response: Response):
        b = await json_body(request)
        if cfg.pin_hash:
            raise HTTPException(409, "ya está configurado: entra con tu PIN")
        _setup_code(request, str(b.get("code", "")))
        pin = str(b.get("pin", ""))
        if not PIN_RE.match(pin):
            raise HTTPException(400, "el PIN tiene que tener de 4 a 12 números")
        mods, secrets = {}, {}
        for name, ch in (b.get("modules") or {}).items():
            if name not in CATALOG or not isinstance(ch, dict):
                raise HTTPException(400, f"modules.{name}: módulo desconocido")
            values = dict(ch.get("values") or {})
            secrets[name] = {k: str(values.pop(k) or "") for k in list(values) if k in secret_keys(name)}
            mods[name] = {"enabled": ch.get("enabled"), "values": values}
        general = {k: b[k] for k in ("name", "timezone") if b.get(k)}
        try:
            apply_changes(cfg.config_path, {"PANEL_DATA": cfg.data_dir}, general=general, modules=mods)
        except ConfigError as e:
            raise HTTPException(400, str(e))
        for name, vals in secrets.items():
            if vals:
                save_secrets(cfg.data_dir, name, vals)
        cfg.pin_hash = save_pin(cfg.data_dir, pin)
        limiter.ok(_ip(request))
        https = request.url.scheme == "https"  # con un proxy de confianza, uvicorn ya lo ha puesto a https
        response.set_cookie(auth.COOKIE, auth.make_token(cfg.secret), max_age=auth.TOKEN_MAX_AGE,
                            httponly=True, samesite="strict", secure=https)
        restart()
        return {"ok": True}

    # ---------- Tienda de módulos ----------

    def _module_view(name: str) -> dict:
        values = saved_values(cfg.config_path, name)
        secrets = load_secrets(cfg.data_dir).get(name, {})
        for k in secret_keys(name):
            values[k] = {"set": bool(secrets.get(k))}
        return {"name": name, **CATALOG[name], "enabled": cfg.enabled(name), "values": values,
                "deps": ctx.deps.view(name)}

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

    @app.post("/api/modules/{name}/check", dependencies=authed)
    async def check(name: str, request: Request):
        from .requirements import check_module
        if name not in CATALOG:
            raise HTTPException(404, "módulo desconocido")
        given = (await json_body(request)).get("values") or {}
        values = {**saved_values(cfg.config_path, name), **load_secrets(cfg.data_dir).get(name, {})}
        values.update({k: v for k, v in given.items() if v not in (None, "") or k not in secret_keys(name)})
        if name == "jellyfin":
            values.setdefault("jfa_user", cfg.jfa_user)
            values.setdefault("jfa_pass", cfg.jfa_pass)
        return await check_module(name, values, ctx.ssh)

    @app.get("/api/deps/{name}", dependencies=authed)
    async def deps_job(name: str):
        job = ctx.deps.jobs.get(name)
        if not job:
            raise HTTPException(404, "no hay ninguna descarga de ese módulo")
        return job.view()

    @app.post("/api/deps/{name}/retry", dependencies=authed)
    async def deps_retry(name: str):
        if name not in ctx.deps_pending:
            raise HTTPException(409, "ese módulo no está esperando dependencias")
        start_install([name])
        return {"ok": True}

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
    # La interfaz, con versión en la URL y comprimida (assets.py); lo de sin versión queda para sw.js, iconos…
    mod_dirs = {n: d for n in modules.MODULES if loaded(n) and (d := modules.web_dir(n))}
    assets = Assets(cfg.web_dir, mod_dirs)

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    async def index(request: Request):
        return assets.index(request.headers)

    @app.get("/api/version", include_in_schema=False)
    async def version():
        """La versión de la interfaz: una pestaña abierta de antes de actualizar ve que no es la suya y se recarga."""
        return {"v": assets.version()}

    @app.get("/v/{ver}/{path:path}", include_in_schema=False)
    async def versioned(ver: str, path: str, request: Request):
        f = assets.resolve(path)
        if not f:
            raise HTTPException(404)
        # Una versión que no es la actual (una pestaña abierta de antes de actualizar): lo de ahora, sin guardarlo
        return assets.response(f, request.headers, IMMUTABLE if ver == assets.version() else "no-cache")

    app.add_middleware(GzipJSON)
    for name, d in mod_dirs.items():
        app.mount(f"/modules/{name}", Static(directory=d), name=f"module-{name}")
    app.mount("/", Static(directory=cfg.web_dir, html=True, check_dir=False), name="web")
    return app


app = create_app(settings)
