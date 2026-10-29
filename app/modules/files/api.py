import mimetypes
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ... import auth
from ...core import json_body
from .files import Files
from .fs import FilesError, NotFound, SftpFS

# Lo que se puede ver en el navegador sin descargar. Nada que ejecute código (html, svg…): se serviría desde el
# mismo origen que el panel.
INLINE = re.compile(r"^(image/(png|jpeg|gif|webp|avif|bmp)|video/.*|audio/.*|application/pdf|text/plain)$")
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _disposition(kind: str, name: str) -> str:
    ascii_name = name.encode("ascii", "replace").decode().replace('"', "_").replace("?", "_")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def setup(ctx) -> APIRouter:
    files = Files(SftpFS(ctx.ssh), ctx.cfg.mod("files").get("roots"))
    ctx.files = files
    ctx.busy_checks.append(files.busy)
    r = APIRouter(prefix="/api/files", dependencies=[Depends(auth.require_auth)])

    async def run(coro):
        try:
            return await coro
        except NotFound as e:
            raise HTTPException(404, str(e))
        except FilesError as e:
            raise HTTPException(400, str(e))

    @r.get("/roots")
    async def roots():
        return {"roots": await run(files.roots())}

    @r.get("/list")
    async def listing(path: str):
        return await run(files.listing(path))

    @r.get("/text")
    async def text(path: str):
        return await run(files.read_text(path))

    @r.put("/text")
    async def save_text(request: Request):
        b = await json_body(request)
        return await run(files.write_text(b.get("path"), b.get("content"), b.get("mtime")))

    @r.post("/new")
    async def new(request: Request):
        b = await json_body(request)
        return await run(files.new(b.get("path"), b.get("name"), bool(b.get("dir"))))

    @r.post("/rename")
    async def rename(request: Request):
        b = await json_body(request)
        return await run(files.rename(b.get("path"), b.get("name")))

    @r.post("/paste")
    async def paste(request: Request):
        b = await json_body(request)
        return await run(files.paste(b.get("sources"), b.get("dest"), bool(b.get("move"))))

    @r.post("/delete")
    async def delete(request: Request):
        return await run(files.delete((await json_body(request)).get("paths")))

    @r.get("/jobs/{jid}")
    async def job(jid: str):
        try:
            return files.job(jid)
        except NotFound as e:
            raise HTTPException(404, str(e))

    @r.put("/upload")
    async def upload(path: str, name: str, request: Request):
        return await run(files.upload(path, name, request.stream()))

    @r.get("/download")
    async def download(path: str, request: Request, inline: bool = False):
        p, st = await run(files.file(path))
        headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox", "Cache-Control": "no-store"}
        if st["dir"]:
            name, chunks = await run(files.tar(p))
            return StreamingResponse(chunks, media_type="application/x-tar",
                                     headers={**headers, "Content-Disposition": _disposition("attachment", name)})
        name = p.rsplit("/", 1)[-1]
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        show = inline and INLINE.match(mime)
        size, start, end, status = st["size"], 0, st["size"], 200
        if m := RANGE_RE.match(request.headers.get("range", "")):
            a, b = m.groups()
            if a:
                start, end = int(a), min(size, int(b) + 1) if b else size
            elif b:
                start = max(0, size - int(b))
            if start >= size or start >= end:
                raise HTTPException(416, "rango fuera del archivo", headers={"Content-Range": f"bytes */{size}"})
            status = 206
            headers["Content-Range"] = f"bytes {start}-{end - 1}/{size}"
        headers.update({"Accept-Ranges": "bytes", "Content-Length": str(end - start),
                        "Content-Disposition": _disposition("inline" if show else "attachment", name)})
        return StreamingResponse(files.fs.read(p, start, end), status_code=status,
                                 media_type=mime if show else "application/octet-stream", headers=headers)

    return r
