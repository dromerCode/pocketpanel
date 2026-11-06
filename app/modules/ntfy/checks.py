import httpx


async def http_checks(v: dict, http: httpx.AsyncClient) -> list[dict]:
    server = (v.get("server") or "https://ntfy.sh").strip().rstrip("/")
    try:
        r = await http.get(f"{server}/v1/health")
        ok = r.status_code == 200 and r.json().get("healthy") is True
        detail = "" if ok else f"respondió {r.status_code}"
    except (httpx.HTTPError, ValueError, AttributeError) as e:
        ok, detail = False, str(e) or type(e).__name__
    out = [{"label": f"{server} responde", "ok": ok, "level": "error", "detail": detail}]
    if ok and v.get("token"):
        try:
            r = await http.get(f"{server}/v1/account", headers={"Authorization": f"Bearer {v['token']}"})
            ok, detail = r.status_code == 200, "" if r.status_code == 200 else f"respondió {r.status_code}"
        except httpx.HTTPError as e:
            ok, detail = False, str(e) or type(e).__name__
        out.append({"label": "El token es válido", "ok": ok, "level": "error", "detail": detail})
    return out
