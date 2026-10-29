"""Acceso a los archivos del host por SFTP (el mismo SSH que usa el resto del panel).

Files (files.py) solo habla con esta interfaz; los tests le ponen una que trabaja en el disco local."""
import asyncio
import stat
from contextlib import asynccontextmanager

import asyncssh

from ...ssh import SSHError

CHUNK = 256 * 1024


class FilesError(Exception):
    """Algo que no se puede hacer (la API contesta 400 con el mensaje)."""


class NotFound(FilesError):
    pass


@asynccontextmanager
async def _errors(path: str):
    try:
        yield
    except asyncssh.SFTPNoSuchFile as e:
        raise NotFound(f"no existe: {path}") from e
    except asyncssh.SFTPPermissionDenied as e:
        raise FilesError(f"sin permiso: {path}") from e
    except asyncssh.SFTPError as e:
        raise FilesError(f"{path}: {e.reason or e}") from e
    except asyncssh.Error as e:
        raise SSHError(str(e)) from e


def _entry(name: str, a) -> dict:
    mode = a.permissions or 0
    return {"name": name, "dir": stat.S_ISDIR(mode), "link": stat.S_ISLNK(mode), "size": a.size or 0,
            "mtime": a.mtime or 0}


class SftpFS:
    def __init__(self, ssh):
        self.ssh = ssh
        self._sftp = self._conn = None
        self._lock = asyncio.Lock()

    async def sftp(self):
        conn = await self.ssh.conn()
        async with self._lock:
            if self._sftp is None or self._conn is not conn:
                try:
                    self._sftp = await conn.start_sftp_client()
                except asyncssh.Error as e:
                    raise SSHError(f"SFTP: {e}") from e
                self._conn = conn
        return self._sftp

    async def realpath(self, path: str) -> str:
        s = await self.sftp()
        async with _errors(path):
            return await s.realpath(path)

    async def stat(self, path: str) -> dict | None:
        s = await self.sftp()
        try:
            async with _errors(path):
                return _entry(path.rsplit("/", 1)[-1], await s.stat(path))
        except NotFound:
            return None

    async def listdir(self, path: str) -> list[dict]:
        s = await self.sftp()
        async with _errors(path):
            names = [n for n in await s.readdir(path) if n.filename not in (".", "..")]
        out = [_entry(n.filename, n.attrs) for n in names]
        links = [e for e in out if e["link"]]

        async def follow(e):  # un enlace a una carpeta se abre como carpeta
            t = await self.stat(f"{path.rstrip('/')}/{e['name']}")
            if t:
                e.update(dir=t["dir"], size=t["size"])
        await asyncio.gather(*map(follow, links))
        return out

    async def mkdir(self, path: str) -> None:
        s = await self.sftp()
        async with _errors(path):
            await s.mkdir(path)

    async def rename(self, old: str, new: str) -> None:
        s = await self.sftp()
        async with _errors(old):
            await s.rename(old, new)  # el de SFTP no pisa: si `new` existe, falla

    async def remove(self, path: str) -> None:
        s = await self.sftp()
        async with _errors(path):
            await s.remove(path)

    async def free(self, path: str) -> dict | None:
        s = await self.sftp()
        try:
            v = await s.statvfs(path)
        except asyncssh.Error:
            return None
        return {"free": v.bavail * v.frsize, "total": v.blocks * v.frsize}

    async def read(self, path: str, start: int = 0, end: int | None = None):
        """Trozos del archivo de `start` a `end` (sin incluir)."""
        s = await self.sftp()
        async with _errors(path):
            f = await s.open(path, "rb")
        try:
            pos = start
            while end is None or pos < end:
                async with _errors(path):
                    data = await f.read(CHUNK if end is None else min(CHUNK, end - pos), pos)
                if not data:
                    break
                pos += len(data)
                yield data
        finally:
            await f.close()

    async def write(self, path: str, chunks) -> int:
        """Escribe lo que llega (de 1 MB en 1 MB: SFTP va mejor con trozos grandes). Devuelve los bytes."""
        s = await self.sftp()
        n, buf = 0, bytearray()
        async with _errors(path):
            async with s.open(path, "wb") as f:
                async for c in chunks:
                    buf += c
                    if len(buf) >= 1 << 20:
                        await f.write(bytes(buf), n)
                        n += len(buf)
                        buf.clear()
                if buf:
                    await f.write(bytes(buf), n)
                    n += len(buf)
        return n

    async def run(self, cmd: str) -> tuple[int, str]:
        """Un comando en el host sin límite de tiempo (una copia grande tarda): (código, stderr)."""
        conn = await self.ssh.conn()
        try:
            r = await conn.run(cmd, check=False)
        except asyncssh.Error as e:
            raise SSHError(str(e)) from e
        return r.exit_status or 0, (r.stderr or "").strip()

    async def stream(self, cmd: str):
        """La salida binaria de un comando (tar), a trozos."""
        conn = await self.ssh.conn()
        try:
            proc = await conn.create_process(cmd, encoding=None)
        except asyncssh.Error as e:
            raise SSHError(str(e)) from e
        try:
            while data := await proc.stdout.read(CHUNK):
                yield data
        finally:
            proc.close()
