import asyncio
import copy
import json
import logging
import time
from pathlib import Path

from ...jobs import Job

log = logging.getLogger("pocketpanel.updater")
OLD_SUFFIX = "-pocketpanel-old"
ALL = "__todas__"
WAIT_SECONDS = 90


def split_image(ref: str) -> tuple[str, str]:
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        repo, _, tag = ref.rpartition(":")
        return repo, tag
    return ref, "latest"


def build_create_body(c: dict, old_image: dict) -> tuple[str, dict]:
    """Cuerpo de POST /containers/create para recrear `c` igual, pero dejando que la imagen nueva
    ponga sus propios valores por defecto (env, labels, cmd… que venían de la vieja)."""
    name = c["Name"].lstrip("/")
    cfg = copy.deepcopy(c["Config"])
    icfg = old_image.get("Config") or {}

    img_env = set(icfg.get("Env") or [])
    cfg["Env"] = [e for e in cfg.get("Env") or [] if e not in img_env]
    img_labels = icfg.get("Labels") or {}
    cfg["Labels"] = {k: v for k, v in (cfg.get("Labels") or {}).items() if img_labels.get(k) != v}
    for k in ("Cmd", "Entrypoint", "WorkingDir", "User", "ExposedPorts", "Volumes", "Healthcheck", "StopSignal", "Shell"):
        if k in cfg and cfg[k] == icfg.get(k):
            del cfg[k]

    host = copy.deepcopy(c["HostConfig"])
    mode = host.get("NetworkMode") or ""
    if cfg.get("Hostname") == c["Id"][:12] or mode == "host" or mode.startswith("container:"):
        cfg.pop("Hostname", None)
        cfg.pop("Domainname", None)

    # Volúmenes anónimos: reutilizarlos (si no, el contenedor nuevo empieza con volúmenes vacíos)
    binds = list(host.get("Binds") or [])
    covered = {b.split(":")[1] for b in binds if ":" in b} | {m.get("Target") for m in host.get("Mounts") or []}
    for m in c.get("Mounts") or []:
        if m.get("Type") == "volume" and m.get("Destination") not in covered:
            binds.append(f"{m['Name']}:{m['Destination']}")
    host["Binds"] = binds
    cfg["HostConfig"] = host

    if mode not in ("host", "none") and not mode.startswith("container:"):
        eps = {}
        for net, ep in (c.get("NetworkSettings") or {}).get("Networks", {}).items():
            aliases = [a for a in (ep.get("Aliases") or []) if a != c["Id"][:12]]
            e = {"Aliases": aliases or None}
            if ep.get("IPAMConfig"):
                e["IPAMConfig"] = ep["IPAMConfig"]
            if ep.get("Links"):
                e["Links"] = ep["Links"]
            eps[net] = e
        if eps:
            cfg["NetworkingConfig"] = {"EndpointsConfig": eps}
    return name, cfg


class Updater:
    """Busca imágenes nuevas y actualiza contenedores recreándolos (con vuelta atrás si fallan)."""

    def __init__(self, docker, http, backup=None, push=None, skip=("pocketpanel",), data_dir: str | None = None):
        self.docker, self.http, self.backup, self.push = docker, http, backup, push
        self.skip = set(skip)
        self.jobs: dict[str, Job] = {}
        self.results: dict[str, dict] = {}
        self.checked_at: int | None = None
        self.checking = False
        self.file = Path(data_dir) / "updates.json" if data_dir else None
        try:
            saved = json.loads(self.file.read_text()) if self.file else {}
            self.results, self.checked_at = saved.get("results", {}), saved.get("checked_at")
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        if self.file:
            try:
                self.file.write_text(json.dumps({"results": self.results, "checked_at": self.checked_at}))
            except OSError as e:
                log.warning("no se pudo guardar updates.json: %s", e)

    # ---------- comprobar ----------

    async def _check_image(self, ref: str) -> dict:
        from .registry import digest_matches, parse_ref, remote_digest
        img = await self.docker.inspect_image(ref)
        if not img or not img.get("RepoDigests"):
            return {"status": "local"}
        parsed = parse_ref(ref)
        if not parsed:
            return {"status": "pinned"}
        registry, repo, _tag = parsed
        try:
            d = await remote_digest(self.http, *parsed)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "error": str(e)[:120]}
        return {"status": "ok" if digest_matches(img["RepoDigests"], registry, repo, d) else "update"}

    async def check(self) -> dict:
        if self.checking:
            return self.results
        self.checking = True
        try:
            cs = await self.docker.containers()
            refs = {}
            for c in cs:
                name = c["Names"][0].lstrip("/")
                if name in self.skip or name.endswith(OLD_SUFFIX):
                    continue
                refs.setdefault(c["Image"], []).append(name)
            before = {n for n, r in self.results.items() if r["status"] == "update"}
            results = {}
            for ref, names in refs.items():
                try:
                    r = await self._check_image(ref)
                except Exception as e:  # noqa: BLE001
                    r = {"status": "error", "error": str(e)[:120]}
                for n in names:
                    results[n] = {**r, "image": ref}
                await asyncio.sleep(0.3)  # sin prisas con los registros
            self.results = results
            self.checked_at = int(time.time())
            now = sorted(n for n, r in results.items() if r["status"] == "update")
            if self.push and set(now) - before:
                await self.push.send("Actualizaciones disponibles", ", ".join(now), "/#services/updates")
            return results
        finally:
            # aunque falle, no reintentar en cada vuelta del monitor (límites de los registros)
            self.checked_at = self.checked_at or int(time.time())
            self.checking = False
            self._save()

    # ---------- actualizar ----------

    def start_all(self) -> Job:
        """Actualiza todo lo que tiene versión nueva, uno a uno, con un único backup al principio."""
        if any(x.status == "running" for x in self.jobs.values()):
            raise ValueError("ya hay una actualización en marcha")
        names = sorted(n for n, r in self.results.items() if r.get("status") == "update" and n not in self.skip)
        if not names:
            raise ValueError("no hay nada que actualizar")
        j = self.jobs[ALL] = Job(ALL)
        asyncio.create_task(self._run_all(j, names))
        return j

    async def _run_all(self, j: Job, names: list[str]) -> None:
        ok, failed = [], []
        try:
            if self.backup:
                j.log(f"Backup de la config antes de actualizar {len(names)} contenedores…")
                r = await self.backup.run(label="antes-actualizar-todo")
                if not r["ok"]:
                    raise RuntimeError(f"el backup falló ({r['error']}), no actualizo nada")
                j.log(f"Backup hecho: {r['snapshot']}")
            for i, name in enumerate(names, 1):
                j.log(f"── [{i}/{len(names)}] {name}")
                sub = self.jobs[name] = Job(name)
                await self._run(sub, force=False, backup=False, notify=False)
                for line in sub.lines:
                    j.lines.append("   " + line)
                (ok if sub.status in ("ok", "noop") else failed).append(name)
            j.status = "ok" if not failed else "failed"
            j.log(f"Terminado: {len(ok)} actualizados" + (f", fallaron (vueltos atrás): {', '.join(failed)}" if failed else ""))
        except Exception as e:  # noqa: BLE001
            j.status = "failed"
            j.log(f"✗ Error: {e}")
        if self.push:
            body = f"{len(ok)} actualizados" + (f"; fallaron: {', '.join(failed)}" if failed else "") if ok or failed else j.lines[-1]
            await self.push.send("Actualización de todo", body[:200], "/#services")

    def start(self, name: str, force: bool = False) -> Job:
        if name in self.skip:
            raise ValueError("este contenedor no se actualiza desde aquí")
        j = self.jobs.get(name)
        if j and j.status == "running":
            return j
        if any(x.status == "running" for x in self.jobs.values()):
            raise ValueError("ya hay otra actualización en marcha")
        j = self.jobs[name] = Job(name)
        asyncio.create_task(self._run(j, force))
        return j

    async def _wait_healthy(self, name: str, j: Job) -> str | None:
        """None si arranca bien; si no, el motivo."""
        deadline = time.time() + WAIT_SECONDS
        stable_since = health = None
        while time.time() < deadline:
            await asyncio.sleep(3)
            st = (await self.docker.inspect_container(name))["State"]
            if st.get("Restarting") or (not st.get("Running") and st.get("Status") in ("exited", "dead")):
                return f"el contenedor no se mantiene arrancado ({st.get('Status')}, código {st.get('ExitCode')})"
            health = (st.get("Health") or {}).get("Status")
            if health == "unhealthy":
                return "el healthcheck dice unhealthy"
            if health == "healthy":
                return None
            if st.get("Running") and not health:
                stable_since = stable_since or time.time()
                if time.time() - stable_since >= 20:
                    return None
        if health == "starting":
            j.log("el healthcheck sigue en 'starting', lo doy por bueno porque está en marcha")
            return None
        return "no arrancó a tiempo"

    async def _run(self, j: Job, force: bool, backup: bool = True, notify: bool = True) -> None:
        d, name = self.docker, j.name
        old_name = name + OLD_SUFFIX
        renamed = created = False
        try:
            c = await d.inspect_container(name)
            ref = c["Config"]["Image"]
            old_img = await d.inspect_image(c["Image"]) or {}
            if self.backup and backup:
                j.log("Backup de la config antes de tocar nada…")
                r = await self.backup.run(label=f"antes-{name.lower()[:30]}")
                if not r["ok"]:
                    raise RuntimeError(f"el backup falló ({r['error']}), no sigo")
                j.log(f"Backup hecho: {r['snapshot']}")
            repo, tag = split_image(ref)
            j.log(f"Descargando {repo}:{tag}…")
            await d.pull(repo, tag, on_line=lambda l: None)
            new_img = await d.inspect_image(ref)
            if new_img and new_img["Id"] == c["Image"] and not force:
                j.status = "noop"
                j.log("Ya tenía la última imagen, no hay nada que hacer.")
                self.results.setdefault(name, {})["status"] = "ok"
                return
            _, body = build_create_body(c, old_img)
            j.log("Parando el contenedor viejo…")
            await d.stop(name)
            await d.remove(old_name)  # restos de un intento anterior
            await d.rename(name, old_name)
            renamed = True
            j.log("Creando el contenedor nuevo con la misma configuración…")
            await d.create(name, body)
            created = True
            await d.start(name)
            j.log(f"Arrancado, compruebo que se queda en marcha (hasta {WAIT_SECONDS} s)…")
            why = await self._wait_healthy(name, j)
            if why:
                raise RuntimeError(why)
            await d.remove(old_name)
            j.status = "ok"
            j.log("✓ Actualizado. Contenedor viejo borrado (la imagen anterior queda en Docker por si acaso).")
            self.results[name] = {**self.results.get(name, {}), "status": "ok", "image": ref}
            self._save()
        except Exception as e:  # noqa: BLE001
            j.status = "failed"
            j.log(f"✗ Error: {e}")
            if renamed:
                j.log("Vuelvo al contenedor anterior…")
                try:
                    if created:
                        await d.remove(name)
                    await d.rename(old_name, name)
                    await d.start(name)
                    j.log("Contenedor anterior restaurado y arrancado.")
                except Exception as e2:  # noqa: BLE001
                    j.log(f"✗✗ No pude restaurarlo solo: {e2}. Está como {old_name}.")
            if self.push and notify:
                await self.push.send(f"Actualización de {name} fallida", str(e)[:200], "/#services")
