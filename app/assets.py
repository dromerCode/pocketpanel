"""La interfaz servida con versión en la URL y comprimida.

Todo lo de web/ y de la carpeta web/ de cada módulo activo se sirve también en /v/<versión>/… (los módulos en
/v/<versión>/modules/<nombre>/…). La versión es un resumen de los archivos, así que una URL con versión no cambia
nunca: el navegador la guarda para siempre (immutable) y al abrir el panel no pregunta por nada; al actualizar el
panel cambia la versión y con ella todas las URL. index.html es lo único que se revalida (no-cache, un 304 si no ha
cambiado) y es quien lleva la versión: en las URL de main.js y app.css, en data-v (para registry.js) y en un import
map que lleva los `import "/js/api.js"` de los módulos a su URL con versión (sin él habría dos copias de api.js).

Lo de texto se manda en gzip si el navegador lo acepta (xterm.js: 289 → 67 KB). Los archivos se leen y comprimen
una vez y se quedan en memoria (la interfaz entera son unos cientos de KB)."""
import gzip
import hashlib
import mimetypes
import time
from pathlib import Path

from starlette.responses import Response

TEXT = (".js", ".css", ".html", ".json", ".svg", ".webmanifest", ".txt", ".map")
MIN_GZIP = 1024
IMMUTABLE = "public, max-age=31536000, immutable"
SCAN_TTL = 2  # s: la versión se recalcula como mucho cada 2 s (en desarrollo los archivos cambian)


def _gzip(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=9, mtime=0)


def accepts_gzip(headers) -> bool:
    return "gzip" in headers.get("accept-encoding", "")


class Assets:
    def __init__(self, web_dir: str, module_dirs: dict[str, str]):
        self.web = Path(web_dir)
        self.mods = {k: Path(v) for k, v in module_dirs.items()}
        self._files: dict[Path, tuple[int, int, bytes, bytes | None]] = {}  # ruta → (mtime, tamaño, datos, gzip)
        self._ver, self._ver_at = "", 0.0

    # --- versión --------------------------------------------------------------------------------------------
    def _all(self):
        for base in (self.web, *self.mods.values()):
            if base.is_dir():
                yield from (p for p in sorted(base.rglob("*")) if p.is_file() and "__pycache__" not in p.parts)

    def version(self) -> str:
        now = time.monotonic()
        if not self._ver or now - self._ver_at > SCAN_TTL:
            h = hashlib.sha1()
            for p in self._all():
                st = p.stat()
                h.update(f"{p}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
            self._ver, self._ver_at = h.hexdigest()[:12], now
        return self._ver

    # --- archivos -------------------------------------------------------------------------------------------
    def resolve(self, path: str) -> Path | None:
        """«js/main.js» o «modules/files/files.js» → el archivo, si existe y no se sale de su carpeta."""
        parts = path.split("/")
        base, rest = self.web, parts
        if parts[0] == "modules":
            if len(parts) < 3 or parts[1] not in self.mods:
                return None
            base, rest = self.mods[parts[1]], parts[2:]
        if any(p in ("", ".", "..") for p in rest):
            return None
        f = (base / "/".join(rest)).resolve()
        if not f.is_file() or not f.is_relative_to(base.resolve()):
            return None
        return f

    def _load(self, f: Path) -> tuple[bytes, bytes | None]:
        st = f.stat()
        hit = self._files.get(f)
        if hit and hit[:2] == (st.st_mtime_ns, st.st_size):
            return hit[2], hit[3]
        data = f.read_bytes()
        gz = _gzip(data) if f.suffix in TEXT and len(data) >= MIN_GZIP else None
        if gz is not None and len(gz) >= len(data):
            gz = None
        self._files[f] = (st.st_mtime_ns, st.st_size, data, gz)
        return data, gz

    def response(self, f: Path, headers, cache: str, body: bytes | None = None) -> Response:
        """El archivo `f` (o `body` en su lugar), en gzip si se puede."""
        if body is None:
            data, gz = self._load(f)
        else:
            data, gz = body, _gzip(body) if len(body) >= MIN_GZIP else None
        mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if f.suffix == ".js":
            mime = "text/javascript"
        h = {"Cache-Control": cache, "Vary": "Accept-Encoding", "X-Content-Type-Options": "nosniff"}
        if gz is not None and accepts_gzip(headers):
            h["Content-Encoding"] = "gzip"
            data = gz
        return Response(data, media_type=mime, headers=h)

    # --- index.html -----------------------------------------------------------------------------------------
    def index(self, headers) -> Response:
        v = self.version()
        etag = f'"{v}"'
        if headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
        f = self.web / "index.html"
        # Los módulos del núcleo, pedidos de golpe en vez de ir descubriéndolos import a import
        pre = "".join(f'<link rel="modulepreload" href="/v/{v}/js/{p.name}">' for p in sorted((self.web / "js").glob("*.js")))
        html = f.read_text().replace("<!--modulepreload-->", pre).replace("{{V}}", v)
        r = self.response(f, headers, "no-cache", html.encode())
        r.headers["ETag"] = etag
        return r


class GzipJSON:
    """Comprime las respuestas JSON de la API de una sola pieza (lo normal). Lo que va a trozos (descargas, logs,
    tareas) pasa tal cual: comprimirlo lo retendría en el búfer y rompería los rangos de las descargas."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not accepts_gzip({k.decode().lower(): v.decode("latin-1")
                                                        for k, v in scope["headers"]}):
            return await self.app(scope, receive, send)
        start = None

        async def wrapped(msg):
            nonlocal start
            if msg["type"] == "http.response.start":
                start = msg
                return
            if start is not None:
                first, start = start, None
                hdrs = {k.lower(): v for k, v in first["headers"]}
                body = msg.get("body", b"")
                if (not msg.get("more_body") and len(body) >= MIN_GZIP and b"content-encoding" not in hdrs
                        and hdrs.get(b"content-type", b"").startswith(b"application/json")):
                    body = _gzip(body)
                    keep = [(k, v) for k, v in first["headers"] if k.lower() not in (b"content-length", b"vary")]
                    first = {**first, "headers": keep + [(b"content-encoding", b"gzip"), (b"vary", b"Accept-Encoding"),
                                                         (b"content-length", str(len(body)).encode())]}
                    msg = {**msg, "body": body}
                await send(first)
            await send(msg)

        await self.app(scope, receive, wrapped)
