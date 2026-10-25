from ...requirements import PRELUDE, chk


def script(v: dict) -> tuple[str, dict]:
    return PRELUDE + chk("tmux", "warn", "command -v tmux"), {"tmux": "tmux instalado (para el modo tmux)"}
