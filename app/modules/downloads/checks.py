import httpx

from .downloads import Arr, DownloadsError, QBit


async def http_checks(v: dict, http: httpx.AsyncClient) -> list[dict]:
    out = []
    if v.get("qbittorrent_url"):
        q = QBit(v["qbittorrent_url"], v.get("qbittorrent_user") or "", v.get("qbittorrent_pass") or "", http=http)
        try:
            await q.torrents()
            ok, detail = True, ""
        except DownloadsError as e:
            ok, detail = False, str(e)
        out.append({"label": "qBittorrent responde y el usuario es correcto", "ok": ok, "level": "error", "detail": detail})
    for kind in ("sonarr", "radarr"):
        if v.get(f"{kind}_url"):
            try:
                await Arr(kind, v[f"{kind}_url"], v.get(f"{kind}_key") or "", http=http).health()
                ok, detail = True, ""
            except DownloadsError as e:
                ok, detail = False, str(e)
            out.append({"label": f"{kind.capitalize()} responde y la API key es correcta", "ok": ok, "level": "error",
                        "detail": detail})
    if not out:
        out.append({"label": "Al menos un servicio configurado", "ok": False, "level": "error",
                    "detail": "pon la URL de qBittorrent, Sonarr o Radarr"})
    return out
