"""Comprueba que unas webs responden y cuánto le queda a su certificado, y avisa de los cambios."""
import asyncio
import socket
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from cryptography import x509

DOWN_AFTER = 2  # fallos seguidos antes de avisar (un fallo suelto no es una caída)


def label(url: str) -> str:
    u = urlsplit(url)
    return (u.netloc + u.path).rstrip("/")


async def check_site(http: httpx.AsyncClient, url: str, timeout: float = 10) -> dict:
    t0 = time.monotonic()
    try:
        r = await http.get(url, timeout=timeout, follow_redirects=True)
        ok = r.status_code < 400
        return {"ok": ok, "status": r.status_code, "ms": round((time.monotonic() - t0) * 1000),
                "error": None if ok else f"HTTP {r.status_code}"}
    except httpx.HTTPError as e:
        return {"ok": False, "status": None, "ms": None, "error": str(e) or type(e).__name__}


def _cert_days_sync(host: str, port: int) -> int | None:
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE  # queremos la fecha aunque esté caducado
    with socket.create_connection((host, port), timeout=8) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as s:
            der = s.getpeercert(binary_form=True)
    if not der:
        return None
    exp = x509.load_der_x509_certificate(der).not_valid_after_utc
    return (exp - datetime.now(timezone.utc)).days


async def cert_days(url: str) -> int | None:
    u = urlsplit(url)
    if u.scheme != "https" or not u.hostname:
        return None
    try:
        return await asyncio.to_thread(_cert_days_sync, u.hostname, u.port or 443)
    except (OSError, ssl.SSLError, ValueError, KeyError):
        return None


class SiteMonitor:
    def __init__(self, opts: dict, http: httpx.AsyncClient | None = None, cert_days=cert_days, today=None):
        self.opts = opts
        self.http = http or httpx.AsyncClient(verify=False)  # la caducidad la miramos aparte
        self.cert_days = cert_days
        self.today = today or (lambda: time.strftime("%Y-%m-%d"))
        self.results: dict[str, dict] = {}
        self._fails: dict[str, int] = {}
        self._down: set[str] = set()
        self._cert_warned: dict[str, str] = {}

    async def _one(self, url: str) -> list:
        r, days = await asyncio.gather(check_site(self.http, url), self.cert_days(url))
        r.update(url=url, name=label(url), cert_days=days, checked=int(time.time()))
        self.results[url] = r
        notes, name = [], r["name"]
        if r["ok"]:
            self._fails[url] = 0
            if url in self._down:
                self._down.discard(url)
                notes.append((f"{name} vuelve a funcionar", "/#status"))
        else:
            self._fails[url] = self._fails.get(url, 0) + 1
            if self._fails[url] >= DOWN_AFTER and url not in self._down:
                self._down.add(url)
                notes.append((f"{name} no responde ({r['error']})", "/#status"))
        warn = self.opts.get("cert_warn_days", 14)
        if days is not None and days <= warn and self._cert_warned.get(url) != self.today():
            self._cert_warned[url] = self.today()
            notes.append((f"El certificado de {name} caduca en {days} días" if days >= 0
                          else f"El certificado de {name} ha caducado", "/#status"))
        return notes

    async def check_all(self) -> list:
        urls = self.opts.get("urls") or []
        for gone in set(self.results) - set(urls):
            self.results.pop(gone)
        out = await asyncio.gather(*(self._one(u) for u in urls))
        return [n for notes in out for n in notes]

    async def tick(self, n: int, now: float) -> list:
        every = max(1, int(self.opts.get("interval", 5)) * 2)  # vueltas de 30 s
        return await self.check_all() if n % every == 0 else []

    def view(self) -> list:
        return [self.results.get(u) or {"url": u, "name": label(u), "ok": None, "status": None, "ms": None,
                                         "error": None, "cert_days": None, "checked": None}
                for u in self.opts.get("urls") or []]
