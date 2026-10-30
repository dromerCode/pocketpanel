import re

KEY_RE = re.compile(r"<ApiKey>([0-9A-Za-z]{20,64})</ApiKey>")
ARR = {"sonarr": 8989, "radarr": 7878}  # el puerto de dentro de su imagen


async def suggest(env) -> dict:
    out = {}
    if (qb := await env.find("qbittorrent")) and (url := qb.url(8080)):
        out["qbittorrent_url"] = {"value": url, "why": qb.where(8080)}
    for app, port in ARR.items():
        c = await env.find(app)
        if not c or not (url := c.url(port)):
            continue
        out[f"{app}_url"] = {"value": url, "why": c.where(port)}
        if conf := c.mounts.get("/config"):
            if m := KEY_RE.search(await env.read(f"{conf}/config.xml")):
                out[f"{app}_key"] = {"value": m[1], "why": f"de {conf}/config.xml"}
    return out
