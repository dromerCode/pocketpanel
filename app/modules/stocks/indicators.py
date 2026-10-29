"""Indicadores técnicos en Python a pelo (antes con pandas): mismas fórmulas, mismos resultados.

Todas reciben listas de precios de la más antigua a la más reciente."""
import math
import statistics


def sma(xs: list[float], n: int) -> float | None:
    return sum(xs[-n:]) / n if len(xs) >= n else None


def ema(xs: list[float], span: int) -> list[float]:
    """Como pandas ewm(span, adjust=False): arranca en el primer valor."""
    a, out = 2 / (span + 1), []
    for x in xs:
        out.append(x if not out else a * x + (1 - a) * out[-1])
    return out


def rsi(closes: list[float], n: int = 14) -> float:
    """Media simple de subidas y bajadas de las últimas n sesiones (la versión de antes, no la de Wilder)."""
    deltas = [b - a for a, b in zip(closes, closes[1:])][-n:]
    if not deltas:
        return 50.0
    gain = sum(max(d, 0) for d in deltas) / len(deltas)
    loss = sum(max(-d, 0) for d in deltas) / len(deltas)
    return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)


def macd(closes: list[float]) -> tuple[bool, bool]:
    """(histograma > 0, ha cambiado de signo en las últimas 4 sesiones)."""
    line = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
    hist = [a - b for a, b in zip(line, ema(line, 9))]
    if not hist:
        return False, False
    last4 = {h > 0 for h in hist[-4:]}
    return hist[-1] > 0, len(hist) >= 4 and len(last4) > 1


def bollinger_pct(closes: list[float], price: float, n: int = 20) -> float | None:
    """Dónde está el precio entre las bandas (0 = banda baja, 100 = banda alta)."""
    if len(closes) < n:
        return None
    w = closes[-n:]
    mid, sd = sum(w) / n, statistics.stdev(w)  # desviación muestral, como pandas
    lo, width = mid - 2 * sd, 4 * sd
    return (price - lo) / width * 100 if width else None


def atr(highs: list[float], lows: list[float], closes: list[float], n: int = 14) -> float | None:
    trs = []
    for i, (h, l) in enumerate(zip(highs, lows)):
        if h is None or l is None:
            trs.append(None)
            continue
        prev = closes[i - 1] if i else None
        trs.append(max(h - l, abs(h - prev), abs(l - prev)) if prev is not None else h - l)
    last = trs[-n:]
    if len(last) < n or any(t is None for t in last):
        return None
    return sum(last) / n


def finite(x) -> float | None:
    return float(x) if x is not None and math.isfinite(float(x)) else None
