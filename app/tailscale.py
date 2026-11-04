"""El widget Tailscale de Estado: los dispositivos de la tailnet, de `tailscale status --json` (no necesita root y
no cambia nada). Si el servidor no tiene Tailscale (ni en el sistema ni en un contenedor), el widget no sale."""
import json
from datetime import datetime

# `tailscale` del sistema, o el de un contenedor de Tailscale si va en Docker (algunos sistemas para NAS lo traen así).
# @absent solo cuando se sabe que no hay: si Docker falla o el contenedor está parado, se dice (parse_status lo da como
# error) y el widget no desaparece. La imagen no basta para saber que es Tailscale: se comprueba que tenga la CLI.
TS = r"""ts() {
  if command -v tailscale >/dev/null 2>&1; then tailscale "$@"; return; fi
  command -v docker >/dev/null 2>&1 || { echo @absent; return 0; }
  ps=$(docker ps -a --format '{{.ID}} {{.Image}} {{.State}}' 2>/dev/null) || { echo "docker no responde"; return 0; }
  for c in $(echo "$ps" | awk '$2 ~ /tailscale/ && $3 == "running" {print $1}'); do
    if docker exec "$c" tailscale version >/dev/null 2>&1; then docker exec "$c" tailscale "$@"; return; fi
  done
  if echo "$ps" | awk '$2 ~ /tailscale/ && $3 != "running" {f=1} END {exit !f}'; then
    echo "El contenedor de Tailscale está parado"; return 0
  fi
  echo @absent
}
"""
SCRIPT = TS + "ts status --json 2>&1"
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


def _load(out: str) -> dict:
    """El JSON de `tailscale status`, aunque el stderr (que se mezcla para poder enseñar los errores) meta avisos."""
    try:
        return json.loads(out)
    except ValueError:
        lines = [x.rstrip() for x in out.splitlines()]
        if "{" not in lines or "}" not in lines:
            raise
        return json.loads("\n".join(lines[lines.index("{"):len(lines) - lines[::-1].index("}")]))


def parse_status(out: str) -> dict:
    if out.strip().endswith("@absent"):  # aunque antes se haya colado algún aviso por stderr
        return {"state": "absent", "devices": []}
    try:
        j = _load(out)
    except ValueError:
        return {"state": "error", "error": (out.strip().splitlines() or ["tailscale no responde"])[-1], "devices": []}
    state = j.get("BackendState") or "?"
    devices = [_device(j["Self"], me=True)] if j.get("Self") else []
    peers = [_device(p) for p in (j.get("Peer") or {}).values()]
    # conectados primero; los demás, el último visto antes
    devices += sorted(peers, key=lambda d: (not d["online"], -(d["last_seen"] or 0), d["name"].lower()))
    return {"state": state, "tailnet": (j.get("CurrentTailnet") or {}).get("Name"), "devices": devices,
            "online": sum(d["online"] for d in devices)}
