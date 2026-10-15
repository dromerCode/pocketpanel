import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException

from .. import auth
from ..downloads import Arr, DownloadsError, DownloadsWatcher, QBit
from ..secrets import load_secrets

HASH_RE = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64})$")


async def _safe(coro):
    try:
        return await coro, None
    except DownloadsError as e:
        return None, str(e)


def setup(ctx) -> APIRouter:
    m = ctx.cfg.mod("downloads")
    s = load_secrets(ctx.cfg.data_dir).get("downloads", {})
    qbit = QBit(m["qbittorrent_url"], s.get("qbittorrent_user", ""), s.get("qbittorrent_pass", "")) \
        if m["qbittorrent_url"] else None
    arrs = [Arr(k, m[f"{k}_url"], s.get(f"{k}_key", "")) for k in ("sonarr", "radarr") if m[f"{k}_url"]]
    ctx.hooks.append(DownloadsWatcher(qbit, arrs, notify_finished=m["notify_finished"]))
    ctx.info["downloads"] = {"qbit": bool(qbit), "arr": [a.kind for a in arrs]}
    r = APIRouter(dependencies=[Depends(auth.require_auth)])

    @r.get("/api/downloads")
    async def downloads():
        out = {"qbit": None, "arr": []}
        if qbit:
            (ts, e1), (tr, e2) = await asyncio.gather(_safe(qbit.torrents()), _safe(qbit.transfer()))
            out["qbit"] = {"ok": not (e1 or e2), "error": e1 or e2, "torrents": ts or [], "transfer": tr}
        for a in arrs:
            (q, e1), (up, e2) = await asyncio.gather(_safe(a.queue()), _safe(a.upcoming()))
            out["arr"].append({"kind": a.kind, "ok": not (e1 or e2), "error": e1 or e2, "queue": q or [],
                               "upcoming": up or []})
        return out

    async def _toggle(hashes: str, verb: str):
        if verb not in ("pause", "resume"):
            raise HTTPException(404, "acción desconocida")
        if not qbit:
            raise HTTPException(404, "qBittorrent no está configurado")
        try:
            await qbit.set_paused(hashes, verb == "pause")
        except DownloadsError as e:
            raise HTTPException(503, str(e))
        return {"ok": True}

    @r.post("/api/downloads/torrents/{h}/{verb}")
    async def toggle_one(h: str, verb: str):
        if verb not in ("pause", "resume"):
            raise HTTPException(404, "acción desconocida")
        if not HASH_RE.match(h):
            raise HTTPException(400, "torrent no válido")
        return await _toggle(h, verb)

    @r.post("/api/downloads/{verb}")
    async def toggle_all(verb: str):
        return await _toggle("all", verb)

    return r
