from collections import Counter

from ...suggest import app_root


async def suggest(env) -> dict:
    """La carpeta donde la mayoría de tus contenedores guardan su config (<carpeta>/<app>/…)."""
    roots = {}
    for c in await env.containers():
        if (r := app_root(c)) and r != "/":
            roots.setdefault(r, []).append(c.name)
    if not roots:
        return {}
    best, _ = Counter({r: len(n) for r, n in roots.items()}).most_common(1)[0]
    names = roots[best]
    return {"source": {"value": best, "why": f"ahí guardan su config {len(names)} contenedores: {', '.join(sorted(names))}"}}
