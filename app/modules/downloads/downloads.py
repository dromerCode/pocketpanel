"""qBittorrent (WebUI API v2) y Sonarr/Radarr (API v3): lo justo para verlo y pausarlo desde el móvil."""
from datetime import datetime, timedelta, timezone

import httpx

PAUSED = {"pausedDL", "pausedUP", "stoppedDL", "stoppedUP"}  # qBittorrent 5 renombró paused → stopped
NO_ETA = 8640000  # lo que devuelve qBittorrent cuando no hay tiempo estimado


class DownloadsError(Exception):
    pass


class QBit:
    def __init__(self, url: str, user: str, password: str, http: httpx.AsyncClient | None = None):
        self.url, self.user, self.password = url.rstrip("/"), user, password
        self.http = http or httpx.AsyncClient(timeout=10)
        self._logged = False

    async def _login(self) -> None:
        try:
            r = await self.http.post(f"{self.url}/api/v2/auth/login", data={"username": self.user,
                                                                            "password": self.password},
                                     headers={"Referer": self.url})
        except httpx.HTTPError as e:
            raise DownloadsError(f"qBittorrent no responde: {e}") from e
        # v4/v5.0 responden 200 "Ok."; desde 5.1, 204 sin cuerpo (y 401 si falla)
        if not (r.status_code == 204 or (r.status_code == 200 and r.text.strip() == "Ok.")):
            raise DownloadsError("qBittorrent rechazó el usuario o la contraseña")
        self._logged = True

    async def _req(self, method: str, path: str, **kw) -> httpx.Response:
        for attempt in (1, 2):
            if not self._logged and self.user:
                await self._login()
            try:
                r = await self.http.request(method, f"{self.url}/api/v2/{path}", **kw)
            except httpx.HTTPError as e:
                raise DownloadsError(f"qBittorrent no responde: {e}") from e
            if r.status_code == 403 and attempt == 1 and self.user:
                self._logged = False  # sesión caducada: entrar otra vez
                continue
            if r.status_code == 403 and not self.user:
                raise DownloadsError("qBittorrent pide usuario y contraseña: ponlos en ⚙ → Descargas")
            return r
        return r

    async def torrents(self) -> list:
        r = await self._req("GET", "torrents/info", params={"sort": "added_on", "reverse": "true"})
        if r.status_code != 200:
            raise DownloadsError(f"qBittorrent: HTTP {r.status_code}")
        return [{"hash": t["hash"], "name": t["name"], "progress": round(t.get("progress", 0), 4),
                 "state": t.get("state"), "paused": t.get("state") in PAUSED, "done": t.get("progress", 0) >= 1,
                 "dl": t.get("dlspeed", 0), "up": t.get("upspeed", 0),
                 "eta": None if t.get("eta", NO_ETA) >= NO_ETA else t.get("eta"), "size": t.get("size")}
                for t in r.json()]

    async def transfer(self) -> dict:
        r = await self._req("GET", "transfer/info")
        if r.status_code != 200:
            raise DownloadsError(f"qBittorrent: HTTP {r.status_code}")
        j = r.json()
        return {"dl": j.get("dl_info_speed", 0), "up": j.get("up_info_speed", 0)}

    async def set_paused(self, hashes: str, paused: bool) -> None:
        """hashes: uno o varios separados por | (o "all"). Prueba la API de v5 y, si no existe, la de v4."""
        for path in (("torrents/stop", "torrents/pause") if paused else ("torrents/start", "torrents/resume")):
            r = await self._req("POST", path, data={"hashes": hashes})
            if r.status_code != 404:
                if r.status_code != 200:
                    raise DownloadsError(f"qBittorrent: HTTP {r.status_code}")
                return
        raise DownloadsError("qBittorrent no sabe pausar (¿versión muy antigua?)")


def _ep(ep: dict) -> str:
    return f"S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}"


class Arr:
    """Sonarr o Radarr."""

    def __init__(self, kind: str, url: str, key: str, http: httpx.AsyncClient | None = None):
        self.kind, self.url, self.key = kind, url.rstrip("/"), key
        self.http = http or httpx.AsyncClient(timeout=10)

    @property
    def name(self) -> str:
        return self.kind.capitalize()

    async def _get(self, path: str, **params):
        try:
            r = await self.http.get(f"{self.url}/api/v3/{path}", params=params, headers={"X-Api-Key": self.key})
        except httpx.HTTPError as e:
            raise DownloadsError(f"{self.name} no responde: {e}") from e
        if r.status_code == 401:
            raise DownloadsError(f"{self.name} rechazó la API key")
        if r.status_code != 200:
            raise DownloadsError(f"{self.name}: HTTP {r.status_code}")
        return r.json()

    async def queue(self) -> list:
        extra = {"includeSeries": "true", "includeEpisode": "true"} if self.kind == "sonarr" else {"includeMovie": "true"}
        out = []
        for q in (await self._get("queue", pageSize=50, **extra)).get("records", []):
            if self.kind == "sonarr" and q.get("series"):
                title = f"{q['series']['title']} {_ep(q.get('episode') or {})}"
            else:
                title = (q.get("movie") or {}).get("title") or q.get("title")
            size, left = q.get("size") or 0, q.get("sizeleft") or 0
            out.append({"title": title, "status": q.get("status"), "progress": round(1 - left / size, 4) if size else None,
                        "timeleft": q.get("timeleft"), "kind": self.kind})
        return out

    async def upcoming(self, days: int = 7, now: str | None = None) -> list:
        start = datetime.fromisoformat(now.replace("Z", "+00:00")) if now else datetime.now(timezone.utc)
        end = start + timedelta(days=days)
        items = await self._get("calendar", start=start.isoformat(), end=end.isoformat(), includeSeries="true")
        out = []
        for it in items:
            if self.kind == "sonarr":
                title = f"{(it.get('series') or {}).get('title', '?')} {_ep(it)}"
                if it.get("title"):
                    title += f" · {it['title']}"
                when = it.get("airDateUtc")
            else:
                title = it.get("title")
                dates = [it.get(k) for k in ("digitalRelease", "physicalRelease", "inCinemas") if it.get(k)]
                future = sorted(d for d in dates if start.isoformat() <= d.replace("Z", "+00:00") <= end.isoformat())
                when = future[0] if future else (dates[0] if dates else None)
            out.append({"title": title, "when": when, "kind": self.kind, "has_file": bool(it.get("hasFile"))})
        return sorted(out, key=lambda x: x["when"] or "")

    async def health(self) -> list:
        return [{"type": h.get("type"), "message": h.get("message")} for h in await self._get("health")]


class DownloadsWatcher:
    """Avisa cuando termina una descarga y cuando Sonarr/Radarr tienen un problema nuevo."""

    def __init__(self, qbit, arrs: list, notify_finished: bool = True):
        self.qbit, self.arrs, self.notify_finished = qbit, arrs, notify_finished
        self._done: dict[str, bool] | None = None
        self._health: dict[str, set] = {}

    async def tick(self, n: int, now: float) -> list:
        notes = []
        if self.qbit and n % 2 == 0:  # cada minuto
            try:
                ts = await self.qbit.torrents()
            except DownloadsError:
                ts = None
            if ts is not None:
                prev, self._done = self._done, {t["hash"]: t["done"] for t in ts}
                if prev is not None and self.notify_finished:
                    notes += [(f"Descargado: {t['name']}", "/#downloads") for t in ts
                              if t["done"] and prev.get(t["hash"]) is False]
        if n % 10 == 0:  # cada 5 min
            for a in self.arrs:
                try:
                    health = await a.health()
                except DownloadsError:
                    continue
                msgs = {h["message"] for h in health if h["type"] in ("warning", "error")}
                prev = self._health.get(a.kind)
                self._health[a.kind] = msgs
                if prev is not None:
                    notes += [(f"{a.kind.capitalize()}: {m}", "/#downloads") for m in sorted(msgs - prev)]
        return notes
