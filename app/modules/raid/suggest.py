import re

MD_RE = re.compile(r"^(md\d+)\s*:\s*active", re.M)


async def suggest(env) -> dict:
    out = {}
    if m := MD_RE.search(await env.read("/proc/mdstat")):
        out["device"] = {"value": f"/dev/{m[1]}", "why": "el RAID activo de /proc/mdstat"}
    if out and (await env.sh("sudo -n -l smartctl >/dev/null 2>&1 && echo yes; true")).strip() == "yes":
        out["sudo"] = {"value": True, "why": "tu usuario puede usar smartctl con sudo sin contraseña"}
    return out
