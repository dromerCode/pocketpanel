async def http_checks(values, http):
    """Que se llega a Yahoo y, si hay Telegram, que el bot existe (curl_cffi aún puede no estar: se usa httpx)."""
    out = []
    try:
        r = await http.get("https://query2.finance.yahoo.com/v8/finance/chart/AAPL", params={"range": "1d"},
                           headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        ok, detail = r.status_code in (200, 429), "" if r.status_code in (200, 429) else f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        ok, detail = False, str(e) or type(e).__name__
    out.append({"label": "Llega a Yahoo Finance", "ok": ok, "level": "error", "detail": detail})
    token = values.get("telegram_token")
    if token:
        try:
            r = await http.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
            ok = r.status_code == 200
            detail = "@" + r.json()["result"]["username"] if ok else f"HTTP {r.status_code}: ¿token mal copiado?"
        except Exception as e:  # noqa: BLE001
            ok, detail = False, str(e) or type(e).__name__
        out.append({"label": "El bot de Telegram responde", "ok": ok, "level": "warn", "detail": detail})
    return out
