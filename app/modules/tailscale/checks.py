from ...requirements import PRELUDE, chk
from .tailscale import TS


def script(v: dict) -> tuple[str, dict]:
    # chk lo ejecuta en otro sh: la función ts tiene que ir dentro del comando
    return (PRELUDE + chk("up", "error", TS + "ts status --json >/dev/null"),
            {"up": "Tailscale funcionando y conectado (en el sistema o en un contenedor)"})
