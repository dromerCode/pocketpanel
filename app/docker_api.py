import asyncio
import json
from typing import AsyncIterator

import httpx


def cpu_percent(prev: dict | None, cur: dict) -> float | None:
    if not prev:
        return None
    try:
        c, p = cur["cpu_stats"], prev["cpu_stats"]
        d_cpu = c["cpu_usage"]["total_usage"] - p["cpu_usage"]["total_usage"]
        d_sys = c["system_cpu_usage"] - p["system_cpu_usage"]
        if d_sys <= 0:
            return 0.0
        return round(d_cpu / d_sys * c.get("online_cpus", 1) * 100, 1)
    except (KeyError, TypeError):
        return None


def mem_usage(stats: dict) -> int | None:
    m = stats.get("memory_stats") or {}
    if "usage" not in m:
        return None
    return m["usage"] - (m.get("stats") or {}).get("inactive_file", 0)


def demux(buf: bytes) -> tuple[bytes, bytes]:
    """Saca stdout/stderr del formato multiplexado de Docker (cabecera de 8 bytes). Devuelve (datos, resto)."""
    out = bytearray()
    while len(buf) >= 8:
        n = int.from_bytes(buf[4:8], "big")
        if len(buf) < 8 + n:
            break
        out += buf[8:8 + n]
        buf = buf[8 + n:]
    return bytes(out), buf


class DockerError(Exception):
    pass


class DockerClient:
    def __init__(self, sock: str):
        self.http = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=sock),
                                      base_url="http://docker", timeout=10)
        self._prev: dict[str, dict] = {}

    async def _get(self, path: str, **params):
        try:
            r = await self.http.get(path, params=params)
        except httpx.HTTPError as e:
            raise DockerError(str(e)) from e
        if r.status_code >= 400:
            raise DockerError(r.text)
        return r.json()

    async def containers(self) -> list:
        return await self._get("/containers/json", all=1)

    async def _stats_one(self, cid: str) -> tuple[str, dict]:
        try:
            cur = await self._get(f"/containers/{cid}/stats", stream=0, **{"one-shot": 1})
        except DockerError:
            return cid, {}
        res = {"cpu": cpu_percent(self._prev.get(cid), cur), "mem": mem_usage(cur)}
        self._prev[cid] = cur
        return cid, res

    async def stats(self, ids: list[str]) -> dict:
        return dict(await asyncio.gather(*(self._stats_one(i) for i in ids)))

    async def action(self, name: str, verb: str) -> None:
        if verb not in ("start", "stop", "restart"):
            raise DockerError("acción no válida")
        try:
            r = await self.http.post(f"/containers/{name}/{verb}", timeout=60)
        except httpx.HTTPError as e:
            raise DockerError(str(e)) from e
        if r.status_code >= 400:
            raise DockerError(r.text)

    async def logs(self, name: str, tail: int = 200) -> AsyncIterator[str]:
        info = await self._get(f"/containers/{name}/json")
        tty = info.get("Config", {}).get("Tty", False)
        params = {"follow": 1, "stdout": 1, "stderr": 1, "tail": tail}
        async with self.http.stream("GET", f"/containers/{name}/logs", params=params, timeout=None) as r:
            if r.status_code >= 400:
                raise DockerError("no se pueden leer los logs")
            rest = b""
            async for chunk in r.aiter_bytes():
                if tty:
                    data = chunk
                else:
                    data, rest = demux(rest + chunk)
                if data:
                    yield data.decode("utf-8", "replace")

    # --- operaciones para recrear contenedores (actualizaciones) ---

    async def _req(self, method: str, path: str, ok=(200, 201, 204, 304), timeout=60, **kw):
        try:
            r = await self.http.request(method, path, timeout=timeout, **kw)
        except httpx.HTTPError as e:
            raise DockerError(f"{method} {path}: {e}") from e
        if r.status_code not in ok:
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            raise DockerError(f"{method} {path}: {msg}")
        return r

    async def inspect_container(self, name: str) -> dict:
        return (await self._req("GET", f"/containers/{name}/json")).json()

    async def inspect_image(self, ref: str) -> dict | None:
        r = await self._req("GET", f"/images/{ref}/json", ok=(200, 404))
        return r.json() if r.status_code == 200 else None

    async def pull(self, repo: str, tag: str, on_line=None) -> None:
        async with self.http.stream("POST", "/images/create", params={"fromImage": repo, "tag": tag}, timeout=None) as r:
            if r.status_code != 200:
                raise DockerError(f"pull {repo}:{tag}: {(await r.aread()).decode()[:300]}")
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("error"):
                    raise DockerError(f"pull: {obj['error']}")
                if on_line and obj.get("status") and not obj.get("progressDetail"):
                    on_line(f"{obj.get('id', '')} {obj['status']}".strip())

    async def stop(self, name: str, t: int = 30) -> None:
        await self._req("POST", f"/containers/{name}/stop", params={"t": t}, timeout=t + 30)

    async def start(self, name: str) -> None:
        await self._req("POST", f"/containers/{name}/start")

    async def rename(self, name: str, new: str) -> None:
        await self._req("POST", f"/containers/{name}/rename", params={"name": new})

    async def create(self, name: str, body: dict) -> str:
        return (await self._req("POST", "/containers/create", params={"name": name}, json=body)).json()["Id"]

    async def remove(self, name: str) -> None:
        # sin v=1: nunca se borran volúmenes
        await self._req("DELETE", f"/containers/{name}", params={"force": 1}, ok=(204, 404))
