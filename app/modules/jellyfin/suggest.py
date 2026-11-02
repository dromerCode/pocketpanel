import shlex


async def suggest(env) -> dict:
    out = {}
    if (jf := await env.find("jellyfin")) and (url := jf.url(8096)):
        out["jellyfin_url"] = {"value": url, "why": jf.where(8096)}
        if conf := jf.mounts.get("/config"):
            db = f"{conf}/data/jellyfin.db"
            if (await env.sh(f"test -s {shlex.quote(db)} && echo yes; true")).strip() == "yes":
                out["db"] = {"value": db, "why": "la base de datos de Jellyfin, en su carpeta de config"}
    if (jfa := await env.find("jfa-go", "jfa")) and (url := jfa.url(8056)):
        out["jfa_url"] = {"value": url, "why": jfa.where(8056)}
    return out
