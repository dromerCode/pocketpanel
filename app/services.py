def _public_port(ports: list) -> int | None:
    tcp = sorted({p["PublicPort"] for p in ports if p.get("Type") == "tcp" and p.get("PublicPort")})
    return tcp[0] if tcp else None


def build_services(containers: list, stats: dict, overrides: dict) -> list:
    out = []
    for c in containers:
        name = c["Names"][0].lstrip("/")
        ov = overrides.get(name) or {}
        if ov.get("hidden"):
            continue
        st = stats.get(c["Id"]) or {}
        out.append({
            "id": c["Id"],
            "name": name,
            "title": ov.get("name") or name,
            "up": c["State"] == "running",
            "state": c["State"],
            "status": c["Status"],
            "icon": ov.get("icon") or (c.get("Labels") or {}).get("icon"),
            "port": ov.get("port") or _public_port(c.get("Ports") or []),
            "url": ov.get("url"),
            "cpu": st.get("cpu"),
            "mem": st.get("mem"),
        })
    out.sort(key=lambda s: s["title"].lower())
    return out
