"""Datos de mercado de un valor y las reglas que dan cada recomendación (sin IA: reglas y estadística).

Los precios van en la moneda del valor (USD casi siempre); `rate` es cuántas unidades de esa moneda vale 1 €."""
import asyncio
import re
import time
from datetime import date, datetime, timezone

from . import indicators as ind
from .yahoo import Yahoo, YahooError, raw

# Grandes cotizadas, líquidas y conocidas de varios sectores: de donde saca candidatos «Descubrir»
DISCOVERY_POOL = {
    "AAPL": "Apple", "MSFT": "Microsoft", "AMZN": "Amazon", "META": "Meta Platforms",
    "NVDA": "NVIDIA", "AVGO": "Broadcom", "AMD": "Advanced Micro Devices", "INTC": "Intel",
    "QCOM": "Qualcomm", "TXN": "Texas Instruments", "ASML": "ASML Holding", "ORCL": "Oracle",
    "CRM": "Salesforce", "ADBE": "Adobe", "NFLX": "Netflix", "DIS": "Walt Disney",
    "V": "Visa", "MA": "Mastercard", "JPM": "JPMorgan Chase", "BAC": "Bank of America",
    "GS": "Goldman Sachs", "UNH": "UnitedHealth", "JNJ": "Johnson & Johnson", "PFE": "Pfizer",
    "LLY": "Eli Lilly", "XOM": "ExxonMobil", "CVX": "Chevron", "COST": "Costco",
    "WMT": "Walmart", "HD": "Home Depot", "NKE": "Nike", "SBUX": "Starbucks",
    "PYPL": "PayPal", "UBER": "Uber", "SHOP": "Shopify", "PLTR": "Palantir",
    "SNOW": "Snowflake", "ARM": "Arm Holdings", "SMCI": "Super Micro Computer",
    "LRCX": "Lam Research", "KLAC": "KLA Corporation", "ANET": "Arista Networks",
    "NOW": "ServiceNow", "PANW": "Palo Alto Networks", "CRWD": "CrowdStrike",
    "DDOG": "Datadog", "NET": "Cloudflare",
    "MU": "Micron Technology", "GOOGL": "Alphabet", "TSM": "Taiwan Semiconductor",
    "AMAT": "Applied Materials", "MRVL": "Marvell Technology", "TSLA": "Tesla",
    "ABBV": "AbbVie", "MS": "Morgan Stanley", "MELI": "MercadoLibre",
    "CAT": "Caterpillar",
}

TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-=^]{0,14}$")


def market_open(meta: dict, now: float | None = None) -> bool:
    """Según el horario de la sesión que da Yahoo para ese mercado (cuenta festivos y husos, no solo NY)."""
    p = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    now = now or time.time()
    return bool(p) and p.get("start", 0) <= now < p.get("end", 0)


async def cnbc_price(y: Yahoo, ticker: str) -> float | None:
    """Segunda fuente para detectar precios raros (validada a céntimo con la de Yahoo)."""
    async def compute():
        try:
            r = await y.s.get(f"https://www.cnbc.com/quotes/{ticker}", timeout=8)
            m = re.search(r'"last":"([\d.]+)"', r.text)
            return float(m.group(1)) if m else None
        except Exception:  # noqa: BLE001 — es solo una comprobación cruzada
            return None
    return await y.cached(f"cnbc:{ticker}", 300, compute)


async def earnings(y: Yahoo, ticker: str) -> dict | None:
    """Próxima presentación de resultados (cambia poco: caché de 6 h)."""
    try:
        s = await y.summary(ticker, "calendarEvents", 6 * 3600)
    except (YahooError, Exception):  # noqa: BLE001
        return None
    dates = [x.get("raw") for x in ((s.get("calendarEvents") or {}).get("earnings") or {}).get("earningsDate") or []]
    dates = [datetime.fromtimestamp(d, timezone.utc).date() for d in dates if d]
    if not dates:
        return None
    d = min(dates)
    return {"date": d.isoformat(), "days_until": (d - date.today()).days}


async def valuation(y: Yahoo, ticker: str) -> dict | None:
    """PEG, PER futuro y consenso de analistas: datos de Yahoo, no opiniones (caché de 1 h)."""
    try:
        s = await y.summary(ticker, "financialData,defaultKeyStatistics,summaryDetail", 3600)
    except (YahooError, Exception):  # noqa: BLE001
        return None
    fd, ks, sd = s.get("financialData"), s.get("defaultKeyStatistics"), s.get("summaryDetail")
    return {"peg": raw(ks, "pegRatio"), "forward_pe": raw(ks, "forwardPE") or raw(sd, "forwardPE"),
            "target_mean": raw(fd, "targetMeanPrice"), "rating": raw(fd, "recommendationKey"),
            "analysts": raw(fd, "numberOfAnalystOpinions")}


def _r(x, n=2):
    x = ind.finite(x)
    return round(x, n) if x is not None else None


async def market_data(y: Yahoo, ticker: str) -> dict:
    """Precio e indicadores de tendencia de un valor (caché de 5 min)."""
    async def compute():
        try:
            d = await y.chart(ticker, "1y", "1d")
        except YahooError as e:
            return {"error": f"sin datos de mercado para {ticker}: {e}"}
        closes = d["c"]
        if not closes:
            return {"error": f"sin datos de mercado para {ticker}"}
        meta = d["meta"]
        currency = meta.get("currency") or "USD"
        try:
            rate = await y.eur_rate(currency)
        except YahooError as e:
            return {"error": str(e)}
        price = ind.finite(meta.get("regularMarketPrice")) or closes[-1]
        prev = closes[-2] if len(closes) >= 2 else closes[-1]
        sma50, sma200 = ind.sma(closes, 50), ind.sma(closes, 200)
        macd_bull, macd_cross = ind.macd(closes)
        atr14 = ind.atr(d["h"], d["l"], closes)
        atr_pct = atr14 / price * 100 if atr14 else None
        ref5 = closes[-6] if len(closes) >= 6 else None
        cross, earn = await asyncio.gather(
            cnbc_price(y, ticker) if currency == "USD" and "." not in ticker else asyncio.sleep(0),
            earnings(y, ticker))
        bb = ind.bollinger_pct(closes, price)
        return {
            "ticker": ticker,
            "name": meta.get("shortName") or meta.get("longName") or ticker,
            "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "",
            "currency": currency, "rate": round(rate, 6),
            "price": round(price, 2),
            "price_eur": round(price / rate, 2),
            "change_pct": _r((price - prev) / prev * 100 if prev else 0) or 0.0,
            "change_5d_pct": _r((price - ref5) / ref5 * 100) if ref5 else None,
            "sma50": _r(sma50), "sma200": _r(sma200),
            "rsi14": round(ind.rsi(closes), 1),
            "week52_low": round(min(closes[-252:]), 2), "week52_high": round(max(closes[-252:]), 2),
            "trend": ("alcista" if sma50 > sma200 else "bajista") if sma50 and sma200 else "sin datos",
            "market_state": "open" if market_open(meta) else "closed",
            "divergence_pct": _r(abs(price - cross) / price * 100) if cross else None,
            "earnings": earn,
            "macd_bullish": macd_bull, "macd_cross_recent": macd_cross,
            "bb_pct": _r(bb, 1),
            "atr_pct": _r(atr_pct),
            # 3×ATR, al estilo «Chandelier Exit»: el stop se adapta a lo que se mueve cada valor (entre -8 y -35 %)
            "atr_stop_pct": round(-min(max(atr_pct * 3, 8), 35), 1) if atr_pct else None,
            "fetched_at": time.time(),
        }
    return await y.cached(f"market:{ticker}", 300, compute)


# ---------- Reglas ----------

def eur(native: float | None, rate: float) -> str:
    if native is None:
        return "—"
    return f"{native / rate:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def caveats(m: dict) -> list[str]:
    out = []
    if m.get("market_state") == "closed":
        out.append("Mercado cerrado: precio del último cierre, no en vivo.")
    if (m.get("divergence_pct") or 0) > 2:
        out.append(f"⚠️ El precio difiere un {m['divergence_pct']:.1f} % de otra fuente (CNBC): revísalo antes de operar.")
    e = m.get("earnings")
    if e and 0 <= e["days_until"] <= 10:
        out.append(f"📅 Resultados en {e['days_until']} días ({e['date']}): riesgo de salto de precio.")
    return out


def indicator_lines(m: dict) -> list[str]:
    lines = [f"RSI14: {m['rsi14']}",
             f"MACD: {'alcista' if m.get('macd_bullish') else 'bajista'}{' (cruce reciente)' if m.get('macd_cross_recent') else ''}"]
    if m.get("bb_pct") is not None:
        lines.append(f"Bandas de Bollinger: {m['bb_pct']:.0f} % (0 = banda baja/sobreventa, 100 = banda alta/sobrecompra)")
    return lines


def auto_zone(m: dict) -> list[float] | None:
    """En tendencia alcista, la franja entre la media de 200 y la de 50 sesiones es la zona clásica para
    «comprar el retroceso»."""
    s50, s200 = m.get("sma50"), m.get("sma200")
    return sorted([round(s200, 2), round(s50, 2)]) if s50 and s200 and s50 > s200 else None


def oversold(m: dict, bb_limit: float = 20) -> bool:
    return m["rsi14"] < 40 or (m.get("bb_pct") is not None and m["bb_pct"] < bb_limit)


def recommend_holding(h: dict, tracking: dict | None, m: dict) -> dict:
    """Para una posición abierta: conservador, proteger el capital antes que perseguir subidas."""
    if "error" in m:
        return {"verdict": "SIN DATOS", "reason": m["error"], "confidence": "N/A", "detail": []}
    rate, price = m["rate"], m["price"]
    entry = h.get("approx_entry_price_usd")  # en la moneda del valor (el nombre viene de cuando todo era USD)
    pl = (price - entry) / entry * 100 if entry else None
    manual_stop = (tracking or {}).get("stop_loss_pct", -15)
    atr_stop = m.get("atr_stop_pct")
    stop = atr_stop if atr_stop is not None else manual_stop
    target = (tracking or {}).get("target")

    why = caveats(m)
    if pl is not None:
        why.append(f"Variación desde la compra: {pl:+.1f} %")
    why.append(f"Tendencia: {m['trend']} (media 50 {eur(m['sma50'], rate)} frente a media 200 {eur(m['sma200'], rate)})")
    if atr_stop is not None:
        why.append(f"Stop según volatilidad (ATR): {atr_stop:.1f} % (el manual sería {manual_stop} %)")
    why += indicator_lines(m)
    hot = m["rsi14"] > 70 or (m.get("bb_pct") or 0) > 95
    c5 = m.get("change_5d_pct")

    if pl is not None and pl <= stop:
        kind = "por volatilidad (ATR)" if atr_stop is not None else "manual"
        return {"verdict": "VENDER", "reason": f"Saltó el stop loss {kind} ({stop:.1f} %).", "detail": why, "confidence": "ALTA"}
    if target and price >= target:
        return {"verdict": "CONSIDERAR VENTA PARCIAL", "reason": "Precio objetivo alcanzado.", "detail": why,
                "confidence": "ALTA" if hot else "MEDIA"}
    # Subida rápida con RSI alto: no hace falta esperar a un objetivo que suele estar lejísimos
    if c5 is not None and c5 > 15 and m["rsi14"] > 65:
        why.insert(0, f"Subida de {c5:+.1f} % en una semana con el RSI en {m['rsi14']}: se está calentando.")
        return {"verdict": "CONSIDERAR VENTA PARCIAL",
                "reason": f"Subida fuerte y rápida ({c5:+.1f} % en una semana) y RSI alto: buen momento para recoger parte.",
                "detail": why, "confidence": "ALTA" if m["rsi14"] > 70 else "MEDIA"}
    if m["trend"] == "bajista" and m["rsi14"] < 40:
        conf = "ALTA" if not m.get("macd_bullish", True) else "MEDIA"
        extra = " El MACD lo confirma." if conf == "ALTA" else ""
        return {"verdict": "VIGILAR", "reason": f"Tendencia bajista y poca fuerza.{extra} No añadir por ahora.",
                "detail": why, "confidence": conf}
    return {"verdict": "MANTENER", "reason": "Sin señal de salida: sigue dentro de la tesis.", "detail": why,
            "confidence": "MEDIA" if pl is not None else "BAJA"}


def recommend_watchlist(w: dict, m: dict, positions_free: bool) -> dict:
    if "error" in m:
        return {"verdict": "SIN DATOS", "reason": m["error"], "confidence": "N/A", "detail": []}
    rate, price, zone = m["rate"], m["price"], w.get("entry_zone")
    source = w.get("zone_source", "manual" if zone else None)
    why = caveats(m)
    if zone:
        note = " (automática, sin análisis fundamental)" if source and source.startswith("auto") else ""
        why.append(f"Zona de entrada: {eur(zone[0], rate)} – {eur(zone[1], rate)}{note}")
    else:
        why.append("Sin zona de entrada")
    why.append(f"Tendencia: {m['trend']}")
    why += indicator_lines(m)

    if not positions_free:
        return {"verdict": "CARTERA LLENA", "reason": "Ya tienes el máximo de posiciones: habría que vender algo antes.",
                "detail": why, "confidence": "ALTA"}
    if zone and zone[0] <= price <= zone[1]:
        conf = "ALTA" if oversold(m) and m.get("macd_bullish") else "MEDIA"
        extra = " El momento (RSI/Bollinger) y el MACD lo confirman." if conf == "ALTA" else ""
        return {"verdict": "ZONA DE COMPRA", "reason": f"El precio está dentro de la zona de entrada.{extra}",
                "detail": why, "confidence": conf}
    if zone and price < zone[0]:
        return {"verdict": "POR DEBAJO DE ZONA", "reason": "Más barato de lo previsto: mira si hay un motivo antes de comprar.",
                "detail": why, "confidence": "BAJA"}
    if zone and price > zone[1]:
        return {"verdict": "ESPERAR", "reason": "Por encima de la zona: no persigas el precio.", "detail": why, "confidence": "MEDIA"}
    return {"verdict": "SIN ZONA", "reason": "Falta una zona de entrada para poder valorar.", "detail": why, "confidence": "BAJA"}


def discover_verdict(m: dict, val: dict | None) -> dict:
    """Lectura técnica y de valoración de un valor que aún no sigues. Pide lo mismo que la lista de seguimiento
    para llamarlo ZONA DE COMPRA; si solo acompaña la técnica, se queda en POSIBLE ENTRADA."""
    if "error" in m:
        return {"verdict": "SIN DATOS", "reason": m["error"], "confidence": "N/A", "detail": []}
    rate, price = m["rate"], m["price"]
    bb, trend_up, macd_bull = m.get("bb_pct"), m["trend"] == "alcista", m.get("macd_bullish")
    why = caveats(m) + indicator_lines(m)
    rating_ok = bool(val and val.get("rating") in ("buy", "strong_buy"))
    if val:
        why.append(f"PEG: {val.get('peg') or '—'} · PER futuro: {_r(val.get('forward_pe'), 1) or '—'} · "
                   f"Analistas: {val.get('rating') or '—'} ({val.get('analysts') or 0}) · "
                   f"Objetivo medio: {eur(val.get('target_mean'), rate)}")
    zone = auto_zone(m)
    if zone and zone[0] <= price <= zone[1] and rating_ok:
        why.insert(0, f"Zona de entrada (automática, media 200 – media 50): {eur(zone[0], rate)} – {eur(zone[1], rate)}")
        return {"verdict": "ZONA DE COMPRA", "candidate": True,
                "reason": "Precio dentro de la zona técnica y valoración/analistas a favor.",
                "detail": why, "confidence": "ALTA" if oversold(m) and macd_bull else "MEDIA"}
    if trend_up and oversold(m, 25):
        return {"verdict": "POSIBLE ENTRADA", "candidate": True,
                "reason": "Tendencia de fondo alcista con un retroceso a corto plazo. La valoración no lo confirma: más débil que una zona de compra.",
                "detail": why, "confidence": "ALTA" if macd_bull else "MEDIA"}
    if m["rsi14"] < 30 or (bb is not None and bb < 10):
        return {"verdict": "SOBREVENTA", "reason": "RSI/Bollinger muy bajos: posible rebote técnico, sin garantías.", "detail": why, "confidence": "BAJA"}
    if m["rsi14"] > 70 or (bb is not None and bb > 90):
        return {"verdict": "SOBRECALENTADO", "reason": "RSI/Bollinger altos: riesgo de corrección a corto plazo.", "detail": why, "confidence": "BAJA"}
    if trend_up and macd_bull:
        return {"verdict": "MOMENTUM ALCISTA", "reason": "Tendencia y MACD al alza.", "detail": why, "confidence": "BAJA"}
    if m["trend"] == "bajista" and not macd_bull:
        return {"verdict": "MOMENTUM BAJISTA", "reason": "Tendencia y MACD a la baja.", "detail": why, "confidence": "BAJA"}
    return {"verdict": "NEUTRAL", "reason": "Sin señal técnica clara ahora mismo.", "detail": why, "confidence": "BAJA"}


def discover_score(m: dict, rec: dict) -> float:
    """Para ordenar de mejor a peor entrada: zona de compra antes que posible entrada; dentro de cada una,
    confianza alta, precio cerca del suelo de la zona, RSI/Bollinger bajos y MACD alcista."""
    score = 100.0 if rec["verdict"] == "ZONA DE COMPRA" else 70.0
    score += {"ALTA": 20, "MEDIA": 10}.get(rec.get("confidence"), 0)
    zone, price = auto_zone(m), m.get("price")
    if zone and price is not None and zone[1] > zone[0]:
        score += (1 - max(0.0, min(1.0, (price - zone[0]) / (zone[1] - zone[0])))) * 10
    rsi = m.get("rsi14")
    score += 10 if rsi < 35 else 5 if rsi < 40 else 0
    score += 5 if (m.get("bb_pct") is not None and m["bb_pct"] < 25) else 0
    score += 5 if m.get("macd_bullish") else 0
    return round(score, 1)
