"""Los dispositivos de la tailnet, de `tailscale status --json` (no necesita root y no cambia nada)."""
import json
from datetime import datetime

SCRIPT = "tailscale status --json 2>&1"
NEVER = "0001-01-01"


def _ts(s: str | None) -> int | None:
    if not s or s.startswith(NEVER):
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _device(p: dict, me: bool = False) -> dict:
    ips = p.get("TailscaleIPs") or []
    return {"name": p.get("HostName") or (p.get("DNSName") or "?").split(".")[0],
            "dns": (p.get("DNSName") or "").rstrip("."), "ip": next((i for i in ips if ":" not in i), ips[0] if ips else None),
            "os": p.get("OS") or "", "online": bool(p.get("Online")) or me, "last_seen": _ts(p.get("LastSeen")),
            "exit_node": bool(p.get("ExitNode")), "me": me}


def parse_status(out: str) -> dict:
    try:
        j = json.loads(out)
    except ValueError:
        return {"state": "error", "error": (out.strip().splitlines() or ["tailscale no responde"])[-1], "devices": []}
    state = j.get("BackendState") or "?"
    devices = [_device(j["Self"], me=True)] if j.get("Self") else []
    peers = [_device(p) for p in (j.get("Peer") or {}).values()]
    # conectados primero; los demás, el último visto antes
    devices += sorted(peers, key=lambda d: (not d["online"], -(d["last_seen"] or 0), d["name"].lower()))
    return {"state": state, "tailnet": (j.get("CurrentTailnet") or {}).get("Name"), "devices": devices,
            "online": sum(d["online"] for d in devices)}
