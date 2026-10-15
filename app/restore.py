import asyncio
import re
import shlex

from .backup import backup_env, host_script
from .updater import Job

SNAP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(-[a-z0-9-]{1,40})?$")
APP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def app_label(app: str) -> str:
    """Etiqueta de la copia de seguridad previa: antes-restaurar-<app> (máx. 40, [a-z0-9-])."""
    slug = re.sub(r"[^a-z0-9-]+", "-", app.lower()).strip("-")
    return ("antes-restaurar-" + slug)[:40].rstrip("-")


def restore_command(snap: str, app: str, mode: str, opts: dict) -> str:
    return host_script("restore.sh", [snap, app, mode], opts)


def apps_from_mounts(mounts: list, source: str) -> list[str]:
    """Subcarpetas de `source` que usa un contenedor (las que se pueden restaurar)."""
    prefix = source.rstrip("/") + "/"
    apps = []
    for m in mounts or []:
        src = m.get("Source") or ""
        if src.startswith(prefix):
            app = src[len(prefix):].split("/")[0]
            if APP_RE.match(app) and app not in apps:
                apps.append(app)
    return apps


def parse_preview(out: str) -> dict:
    m = re.search(r"PP_CHANGES (\d+)", out)
    if not m:
        f = re.search(r"PP_FAIL (.*)", out)
        raise RuntimeError(f.group(1) if f else (out.strip()[-300:] or "sin respuesta"))
    files = [l[len("PP_FILE "):] for l in out.splitlines() if l.startswith("PP_FILE ")]
    return {"changes": int(m.group(1)), "files": files}


class Restorer:
    def __init__(self, ssh, docker, backup, opts: dict, push=None):
        self.ssh, self.docker, self.backup, self.opts, self.push = ssh, docker, backup, opts, push
        self.jobs: dict[str, Job] = {}

    @staticmethod
    def _check(snap: str, app: str) -> None:
        if not SNAP_RE.match(snap or "") or not APP_RE.match(app or ""):
            raise ValueError("copia o carpeta no válida")

    async def snapshots(self) -> list[str]:
        """Solo las copias completas (con la marca .pocketpanel-complete)."""
        e = backup_env(self.opts)
        remote = (f"cd {shlex.quote(e['DEST_PATH'])} && "
                  f"for d in 20*; do [ -f \"$d/.pocketpanel-complete\" ] && echo \"$d\"; done; true")
        out = await self.ssh.run(f"ssh {e['SSH_OPTS']} {shlex.quote(e['DEST_HOST'])} {shlex.quote(remote)}", timeout=20)
        return sorted((l for l in out.split() if SNAP_RE.match(l)), reverse=True)

    async def apps_for(self, container: str) -> list[str]:
        for c in await self.docker.containers():
            if c["Names"][0].lstrip("/") == container:
                return apps_from_mounts(c.get("Mounts"), self.opts["source"])
        return []

    async def _script(self, snap: str, app: str, mode: str, timeout: float) -> str:
        return await self.ssh.run(restore_command(snap, app, mode, self.opts), timeout=timeout)

    async def preview(self, snap: str, app: str) -> dict:
        self._check(snap, app)
        out = await self._script(snap, app, "dry", 180)
        if "a password is required" in out:
            raise RuntimeError("la regla de sudo de pocketpanel no está bien instalada (install-root.sh)")
        return parse_preview(out)

    def start(self, snap: str, app: str) -> Job:
        self._check(snap, app)
        if any(j.status == "running" for j in self.jobs.values()):
            raise ValueError("ya hay una restauración en marcha")
        j = self.jobs[app] = Job(app)
        asyncio.create_task(self._run(j, snap, app))
        return j

    async def _run(self, j: Job, snap: str, app: str) -> None:
        stopped: list[str] = []
        try:
            j.log(f"Copia de seguridad de lo actual antes de restaurar ({app_label(app)})…")
            r = await self.backup.run(label=app_label(app))
            if not r["ok"]:
                raise RuntimeError(f"la copia previa falló ({r['error']}), no sigo")
            j.log(f"Copia previa hecha: {r['snapshot']} (si algo sale mal, se puede volver a ella)")
            for c in await self.docker.containers():
                if c["State"] == "running" and app in apps_from_mounts(c.get("Mounts"), self.opts["source"]):
                    name = c["Names"][0].lstrip("/")
                    if name == "pocketpanel":
                        continue
                    j.log(f"Parando {name}…")
                    await self.docker.stop(name)
                    stopped.append(name)
            j.log(f"Restaurando {self.opts['source'].rstrip('/')}/{app} desde {snap}…")
            out = await self._script(snap, app, "run", 1800)
            if "PP_RESTORED" not in out:
                f = re.search(r"PP_FAIL (.*)", out)
                raise RuntimeError(f.group(1) if f else out.strip()[-300:])
            j.status = "ok"
            j.log("✓ Restaurado.")
        except Exception as e:  # noqa: BLE001
            j.status = "failed"
            j.log(f"✗ Error: {e}")
            if self.push:
                await self.push.send(f"Restauración de {app} fallida", str(e)[:200], "/#services")
        finally:
            for name in stopped:
                try:
                    await self.docker.start(name)
                    j.log(f"{name} arrancado de nuevo.")
                except Exception as e:  # noqa: BLE001
                    j.log(f"✗ No pude arrancar {name}: {e}")
