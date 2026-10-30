# Lo que diga la shell (de login o interactiva: npm -g suele ir en .bashrc) y si no, los sitios de siempre
FIND = r"""for p in "$(bash -lc 'command -v claude' </dev/null 2>/dev/null)" \
         "$(bash -ic 'command -v claude' </dev/null 2>/dev/null)" \
         "$HOME/.local/bin/claude" "$HOME/.npm-global/bin/claude" /usr/local/bin/claude /usr/bin/claude; do
  [ -n "$p" ] && [ -x "$p" ] && { echo "$p"; break; }
done; echo "$HOME"
"""


async def suggest(env) -> dict:
    """Dónde está `claude`, si no es en el sitio de siempre (~/.local/bin/claude)."""
    out = (await env.sh(FIND)).split()
    if len(out) == 2 and out[0] != f"{out[1]}/.local/bin/claude":
        return {"bin": {"value": out[0], "why": "donde está instalado en el servidor"}}
    return {}
