import re
import shlex

# Traefik: traefik.http.routers.<x>.rule = Host(`a.com`) || Host(`b.com`)
HOST_RE = re.compile(r"Host\(`([^`]+)`\)")


async def suggest(env) -> dict:
    """Las webs que publica tu proxy: Nginx Proxy Manager (sus proxy hosts) o Traefik (las etiquetas)."""
    urls, why = [], []
    npm = await env.find("nginx-proxy-manager", "proxymanager", "proxy-manager")
    if npm and (data := npm.mounts.get("/data")):
        conf = shlex.quote(f"{data}/nginx/proxy_host")
        out = await env.sh(f"for f in {conf}/*.conf; do [ -f \"$f\" ] || continue; "
                           "n=$(sed -n 's/^ *server_name \\([^ ;]*\\).*/\\1/p' \"$f\" | head -1); "
                           "grep -q 'listen 443 ssl' \"$f\" && s=https || s=http; echo \"$s $n\"; done")
        found = [f"{s}://{n}" for s, n in (line.split(" ", 1) for line in out.splitlines() if " " in line) if n]
        if found:
            urls += found
            why.append(f"los proxy hosts de Nginx Proxy Manager ({npm.name})")
    traefik = sorted({f"https://{h}" for c in await env.containers() for k, v in c.labels.items()
                      if k.startswith("traefik.http.routers.") and k.endswith(".rule") for h in HOST_RE.findall(v)})
    if traefik:
        urls += traefik
        why.append("las etiquetas de Traefik de tus contenedores")
    urls = sorted(dict.fromkeys(urls), key=lambda u: (u.split("://", 1)[1].removeprefix("www."), u))
    return {"urls": {"value": urls, "why": " y ".join(why)}} if urls else {}
