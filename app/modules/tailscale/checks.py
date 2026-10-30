from ...requirements import PRELUDE, chk


def script(v: dict) -> tuple[str, dict]:
    return (PRELUDE + chk("bin", "error", "command -v tailscale") + chk("up", "error", "tailscale status --json >/dev/null"),
            {"bin": "Tailscale instalado", "up": "Tailscale funcionando y conectado"})
