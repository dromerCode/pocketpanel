"""Dependencias propias de cada módulo: las que no necesita el núcleo y no tienen por qué ir en la imagen.

Un módulo las declara en `app/modules/<nombre>/requirements.txt`. Se descargan solo cuando el módulo está activo, en
`data/deps/<nombre>-<huella>/` (persiste entre reinicios y actualizaciones de la imagen), con `pip --prefix`: lo que
ya trae la imagen no se vuelve a descargar. Al desactivar el módulo o cambiar sus versiones, la carpeta vieja se
borra sola en el siguiente arranque.

Mientras se descargan, el panel arranca sin ese módulo y, al terminar, se reinicia para cargarlo."""
import asyncio
import hashlib
import logging
import os
import shutil
import site
import sys
import sysconfig
from pathlib import Path

from .jobs import Job

log = logging.getLogger("pocketpanel.deps")
MODULES_DIR = Path(__file__).parent / "modules"
OK = ".ok"


def requirements(name: str) -> str:
    """El requirements.txt del módulo (vacío si no tiene)."""
    try:
        return (MODULES_DIR / name / "requirements.txt").read_text()
    except OSError:
        return ""


def _fingerprint(reqs: str) -> str:
    # Cambia si cambian las versiones o el Python de la imagen (las librerías compiladas van por versión)
    tag = f"{sys.implementation.cache_tag}-{sysconfig.get_platform()}"
    return hashlib.sha256(f"{tag}\n{reqs}".encode()).hexdigest()[:12]


def site_dir(prefix: Path) -> Path:
    return Path(sysconfig.get_path("purelib", "posix_prefix", vars={"base": str(prefix), "platbase": str(prefix)}))


class Deps:
    def __init__(self, data_dir: str, pip=None):
        self.root = Path(data_dir) / "deps"
        self.pip = pip or [sys.executable, "-m", "pip"]
        self.jobs: dict[str, Job] = {}

    def needs(self, name: str) -> bool:
        return bool(requirements(name).strip())

    def dir(self, name: str) -> Path:
        return self.root / f"{name}-{_fingerprint(requirements(name))}"

    def ready(self, name: str) -> bool:
        return not self.needs(name) or (self.dir(name) / OK).exists()

    def activate(self, name: str) -> None:
        """Las pone al alcance de `import`. Van al final de sys.path: si algo coincide con la imagen, gana la imagen."""
        if self.needs(name):
            site.addsitedir(str(site_dir(self.dir(name))))

    def prune(self, keep: list[str]) -> list[str]:
        """Borra lo de los módulos apagados y las versiones viejas. Devuelve lo que ha borrado."""
        wanted = {self.dir(n).name for n in keep if self.needs(n)}
        gone = []
        if self.root.is_dir():
            for d in self.root.iterdir():
                if d.name not in wanted:
                    shutil.rmtree(d, ignore_errors=True)
                    gone.append(d.name)
        if gone:
            log.info("dependencias borradas: %s", ", ".join(gone))
        return gone

    async def install(self, name: str) -> Job:
        """Descarga las del módulo en una carpeta temporal y solo la da por buena si pip termina bien."""
        job = self.jobs[name] = Job(name)
        dest = self.dir(name)
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        reqs = tmp / "requirements.txt"
        tmp.mkdir()
        reqs.write_text(requirements(name))
        job.log(f"descargando dependencias de {name}: {', '.join(_names(requirements(name)))}")
        cmd = [*self.pip, "install", "--prefix", str(tmp), "--no-cache-dir", "--disable-pip-version-check",
               "--no-warn-script-location", "--no-input", "--progress-bar", "off", "-r", str(reqs)]
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.STDOUT,
                                                        env={**os.environ, "PIP_NO_CACHE_DIR": "1"})
            async for line in proc.stdout:
                if text := line.decode(errors="replace").rstrip():
                    job.log(text)
            rc = await proc.wait()
        except OSError as e:
            job.log(f"no se pudo lanzar pip: {e}")
            rc = -1
        if rc != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            job.log(f"✗ falló (código {rc}); se reintenta en el próximo arranque o desde Módulos")
            job.status = "failed"
            return job
        shutil.rmtree(dest, ignore_errors=True)
        tmp.rename(dest)
        (dest / OK).write_text(requirements(name))
        job.log(f"✓ listo ({_size(dest)})")
        job.status = "ok"
        return job

    def view(self, name: str) -> dict | None:
        """Para la tienda: si hay que descargar algo y cómo va."""
        if not self.needs(name):
            return None
        job = self.jobs.get(name)
        return {"packages": _names(requirements(name)), "ready": self.ready(name),
                "status": job.status if job else None}


def _names(reqs: str) -> list[str]:
    return [line.split("#")[0].strip() for line in reqs.splitlines() if line.split("#")[0].strip()]


def _size(d: Path) -> str:
    total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    return f"{total / 1e6:.0f} MB"
