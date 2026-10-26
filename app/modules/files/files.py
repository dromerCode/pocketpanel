"""El gestor de archivos: rutas permitidas, listados y las operaciones (copiar, mover, borrar…).

Todo pasa por `resolve`: la ruta se normaliza, se resuelven los enlaces y tiene que quedar dentro de una de las
carpetas de inicio. Copiar, mover y borrar se hacen en el host con cp/mv/rm (rápido aunque sean gigas) como una
tarea en segundo plano que la app sigue."""
import asyncio
import itertools
import posixpath
import secrets
import shlex

from ...jobs import Job
from .fs import FilesError, NotFound

MAX_ITEMS = 5000   # por carpeta
MAX_TEXT = 1 << 20  # lo que se abre en el editor
MAX_BATCH = 1000


def valid_name(name) -> str:
    if not isinstance(name, str) or not name.strip() or name in (".", "..") or "/" in name or "\0" in name \
            or len(name.encode()) > 255:
        raise FilesError("nombre no válido")
    return name


def inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _split(name: str) -> tuple[str, str]:
    """«foto.tar.gz» → («foto», «.tar.gz»); las carpetas y los «.ocultos» no tienen extensión."""
    if name.startswith(".") and name.count(".") == 1:
        return name, ""
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst"):
        if name.lower().endswith(ext):
            return name[:-len(ext)], name[-len(ext):]
    stem, ext = posixpath.splitext(name)
    return stem, ext


class Files:
    def __init__(self, fs, roots=None):
        self.fs = fs
        self.root_specs = [str(r).strip() for r in (roots or ["~"]) if str(r).strip()]
        self.jobs: dict[str, Job] = {}
        self._ids = itertools.count(1)
        self._tasks: set = set()
        self._roots = None

    # --- rutas ---------------------------------------------------------------------------------------------
    async def roots(self) -> list[dict]:
        if self._roots is None:
            home = await self.fs.realpath(".")
            out = []
            for r in self.root_specs:
                if r == "~" or r.startswith("~/"):
                    r = home + r[1:]
                if not r.startswith("/"):
                    continue
                try:
                    real = await self.fs.realpath(posixpath.normpath(r))
                except NotFound:
                    continue  # p. ej. un disco sin montar: no sale
                if all(real != x["path"] for x in out):
                    out.append({"path": real, "name": "Inicio" if real == home else posixpath.basename(real) or "/"})
            self._roots = out
        return self._roots

    async def _real(self, p: str) -> str:
        try:
            return await self.fs.realpath(p)
        except NotFound:
            if p == "/":
                raise
            return posixpath.join(await self._real(posixpath.dirname(p)), posixpath.basename(p))

    async def resolve(self, path, follow: bool = True) -> str:
        """La ruta real (sin «..» ni enlaces) si está dentro de una carpeta de inicio. Con follow=False el último
        trozo no se sigue: para borrar, renombrar, mover o copiar un enlace es el enlace, no a lo que apunta."""
        if not isinstance(path, str) or not path.startswith("/") or "\0" in path:
            raise FilesError("ruta no válida")
        p = "/" + posixpath.normpath(path).lstrip("/")
        if follow or p == "/":
            real = await self._real(p)
        else:
            real = posixpath.join(await self._real(posixpath.dirname(p)), posixpath.basename(p))
        if not any(inside(real, r["path"]) for r in await self.roots()):
            raise FilesError("fuera de las carpetas permitidas (Módulos → Archivos)")
        return real

    async def _root_of(self, p: str) -> str:
        return max((r["path"] for r in await self.roots() if inside(p, r["path"])), key=len)

    async def _dir(self, path) -> str:
        p = await self.resolve(path)
        st = await self.fs.stat(p)
        if not st:
            raise NotFound(f"no existe: {p}")
        if not st["dir"]:
            raise FilesError(f"no es una carpeta: {p}")
        return p

    async def _names(self, d: str) -> set[str]:
        return {e["name"] for e in await self.fs.listdir(d)}  # con los enlaces rotos, que stat no ve

    async def _free_name(self, d: str, name: str, word: str = "") -> str:
        """`d/name` o, si ya existe, «name (copia)», «name (copia 2)»… (o «name (2)», «name (3)»… sin `word`)."""
        taken = await self._names(d)
        stem, ext = _split(name)
        for i in range(1, 1000):
            n = "" if i == 1 else f" ({word})" if word and i == 2 else f" ({word} {i - 1})" if word else f" ({i})"
            cand = name if i == 1 else f"{stem}{n}{ext}"
            if cand not in taken:
                return posixpath.join(d, cand)
        raise FilesError(f"demasiadas copias de {name}")

    # --- lectura ------------------------------------------------------------------------------------------
    async def listing(self, path) -> dict:
        p = await self._dir(path)
        items = await self.fs.listdir(p)
        items.sort(key=lambda e: (not e["dir"], e["name"].casefold()))
        root = await self._root_of(p)
        return {"path": p, "root": root, "parent": None if p == root else posixpath.dirname(p),
                "items": items[:MAX_ITEMS], "truncated": len(items) > MAX_ITEMS, "free": await self.fs.free(p)}

    async def file(self, path) -> tuple[str, dict]:
        p = await self.resolve(path)
        st = await self.fs.stat(p)
        if not st:
            raise NotFound(f"no existe: {p}")
        return p, st

    async def read_text(self, path) -> dict:
        p, st = await self.file(path)
        if st["dir"]:
            raise FilesError("es una carpeta")
        if st["size"] > MAX_TEXT:
            raise FilesError(f"demasiado grande para abrirlo aquí (más de {MAX_TEXT >> 20} MB): descárgalo")
        data = b"".join([c async for c in self.fs.read(p)])
        try:
            if b"\0" in data:
                raise UnicodeDecodeError("utf-8", data, 0, 1, "nul")
            text = data.decode()
        except UnicodeDecodeError:
            raise FilesError("no parece un archivo de texto: descárgalo") from None
        return {"path": p, "content": text, "mtime": st["mtime"]}

    async def write_text(self, path, content, mtime=None) -> dict:
        if not isinstance(content, str) or len(content.encode()) > MAX_TEXT:
            raise FilesError("contenido no válido o demasiado grande")
        p, st = await self.file(path)
        if st["dir"]:
            raise FilesError("es una carpeta")
        if mtime is not None and st["mtime"] != mtime:
            raise FilesError("el archivo ha cambiado desde que lo abriste: vuelve a abrirlo")

        async def one():
            yield content.encode()
        await self.fs.write(p, one())
        return {"path": p, "mtime": (await self.fs.stat(p))["mtime"]}

    # --- cambios rápidos (sin tarea) ------------------------------------------------------------------------
    async def new(self, path, name, is_dir: bool) -> dict:
        d = await self._dir(path)
        target = await self.resolve(posixpath.join(d, valid_name(name)))
        if await self.fs.stat(target):
            raise FilesError(f"ya existe: {name}")
        if is_dir:
            await self.fs.mkdir(target)
        else:
            async def empty():
                yield b""
            await self.fs.write(target, empty())
        return {"path": target}

    async def rename(self, path, name) -> dict:
        p = await self.resolve(path, follow=False)
        if p in [r["path"] for r in await self.roots()]:
            raise FilesError("no se puede renombrar una carpeta de inicio")
        target = await self.resolve(posixpath.join(posixpath.dirname(p), valid_name(name)))
        if target == p:
            return {"path": p}
        if await self.fs.stat(target):
            raise FilesError(f"ya existe: {name}")
        await self.fs.rename(p, target)
        return {"path": target}

    async def upload(self, path, name, chunks) -> dict:
        """Se escribe en un «.parte» y se renombra al final: un corte no deja un archivo a medias con su nombre."""
        d = await self._dir(path)
        target = await self._free_name(d, valid_name(name))
        await self.resolve(target)
        part = posixpath.join(d, f".{posixpath.basename(target)}.{secrets.token_hex(3)}.parte")
        try:
            size = await self.fs.write(part, chunks)
            await self.fs.rename(part, target)
        except BaseException:
            try:
                await self.fs.remove(part)
            except Exception:  # noqa: BLE001
                pass
            raise
        return {"path": target, "size": size}

    # --- tareas (copiar, mover, borrar) ---------------------------------------------------------------------
    def busy(self) -> str | None:
        return "hay una operación con archivos en marcha" if any(j.status == "running" for j in self.jobs.values()) \
            else None

    def _start(self, title: str, work) -> dict:
        jid = str(next(self._ids))
        job = self.jobs[jid] = Job(title)
        for old in list(self.jobs)[:-30]:  # solo las últimas
            if self.jobs[old].status != "running":
                del self.jobs[old]

        async def run():
            try:
                await work(job)
                job.status = "ok"
            except Exception as e:  # noqa: BLE001
                job.log(f"✗ {e}")
                job.status = "failed"
        t = asyncio.create_task(run())
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return {"job": jid, "title": title}

    async def _sh(self, cmd: str) -> None:
        code, err = await self.fs.run(cmd)
        if code:
            raise FilesError(err.splitlines()[-1] if err else f"falló (código {code})")

    async def _many(self, paths) -> list[str]:
        if not isinstance(paths, list) or not paths or len(paths) > MAX_BATCH:
            raise FilesError("lista de rutas no válida")
        out = []
        roots = [r["path"] for r in await self.roots()]
        for x in paths:
            p = await self.resolve(x, follow=False)
            if p in roots:
                raise FilesError(f"{p} es una carpeta de inicio")
            if p not in out:
                out.append(p)
        return out

    async def paste(self, sources, dest, move: bool) -> dict:
        d = await self._dir(dest)
        srcs = await self._many(sources)
        verb = "mover" if move else "copiar"
        for s in srcs:
            if inside(d, s):
                raise FilesError(f"no se puede {verb} una carpeta dentro de sí misma: {posixpath.basename(s)}")

        async def work(job):
            for s in srcs:
                name = posixpath.basename(s)
                if move and posixpath.dirname(s) == d:
                    job.log(f"= {name}: ya estaba aquí")
                    continue
                if name not in await self._names(posixpath.dirname(s)):
                    job.log(f"✗ {name}: ya no existe")
                    continue
                target = await self._free_name(d, name, "" if move else "copia")
                as_ = "" if posixpath.basename(target) == name else f" como «{posixpath.basename(target)}»"
                job.log(f"{'→' if move else '+'} {name}{as_}")
                await self._sh(f"{'mv -n' if move else 'cp -a'} -- {shlex.quote(s)} {shlex.quote(target)}")
            job.log("✓ hecho")
        n = len(srcs)
        return self._start(f"{verb.capitalize()} {n} elemento{'s' * (n != 1)} a {d}", work)

    async def delete(self, paths) -> dict:
        targets = await self._many(paths)

        async def work(job):
            for p in targets:
                job.log(f"− {posixpath.basename(p)}")
                await self._sh(f"rm -rf -- {shlex.quote(p)}")
            job.log("✓ hecho")
        n = len(targets)
        return self._start(f"Borrar {n} elemento{'s' * (n != 1)}", work)

    def job(self, jid: str) -> dict:
        if jid not in self.jobs:
            raise NotFound("esa tarea ya no existe")
        return self.jobs[jid].view()

    # --- descargas -----------------------------------------------------------------------------------------
    async def tar(self, path):
        """Una carpeta como .tar (sin comprimir: lo normal son fotos y vídeos, que no comprimen), a trozos."""
        p, st = await self.file(path)
        if not st["dir"]:
            raise FilesError("no es una carpeta")
        parent, name = posixpath.split(p)
        return f"{name or 'raiz'}.tar", self.fs.stream(f"tar -cf - -C {shlex.quote(parent)} -- {shlex.quote(name)}")
