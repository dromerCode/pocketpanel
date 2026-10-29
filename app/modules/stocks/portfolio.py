"""La cartera: posiciones, lista de seguimiento, «Descubrir», gráficas y avisos (Telegram y push)."""
import asyncio
import bisect
import logging
from datetime import datetime, timezone

import httpx

from ...monitor import due_daily
from . import engine as E
from .pngchart import price_chart
from .store import Store, now_iso
from .yahoo import Yahoo, YahooError

log = logging.getLogger("pocketpanel.stocks")

# rango → (periodo de Yahoo, intervalo, quedarse solo con la última sesión)
RANGES = {"dia": ("5d", "15m", True), "semana": ("5d", "60m", False), "mes": ("1mo", "1d", False),
          "anio": ("1y", "1d", False)}
CONF_EMOJI = {"ALTA": "🟢", "MEDIA": "🟠", "BAJA": "🔴"}


class StocksError(Exception):
    """Algo que el usuario tiene que corregir (400)."""


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(v, what: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise StocksError(f"{what} tiene que ser un número") from None
    if x != x or x in (float("inf"), float("-inf")):
        raise StocksError(f"{what} tiene que ser un número")
    return x


def ticker_of(t: str) -> str:
    t = (t or "").strip().upper()
    if not E.TICKER_RE.match(t):
        raise StocksError("ticker no válido")
    return t


class Stocks:
    def __init__(self, opts: dict, data_dir: str, secrets: dict, yahoo: Yahoo | None = None, http=None, tz=None):
        self.opts, self.tz = opts, tz
        self.store = Store(data_dir)
        self.y = yahoo or Yahoo()
        self.http = http or httpx.AsyncClient(timeout=30)
        self.token = secrets.get("telegram_token") or ""
        self.lock = asyncio.Lock()   # una compra/venta a la vez: los JSON se leen y reescriben enteros
        self._digest_day = None

    @property
    def max_positions(self) -> int:
        return self.opts.get("max_positions") or 3

    def commission(self) -> float:
        try:
            return float(str(self.opts.get("commission") or 0).replace(",", "."))
        except ValueError:
            return 0.0

    async def market(self, t: str) -> dict:
        return await E.market_data(self.y, t)

    # ---------- Cartera ----------

    async def portfolio(self) -> dict:
        hs, ws = self.store.holdings(), self.store.watchlist()
        held = [h["ticker"] for h in hs["holdings"]]
        free = len(held) < self.max_positions
        watch = [w for w in ws["watchlist"] if w["ticker"] not in held]
        markets = await asyncio.gather(*(self.market(t) for t in held + [w["ticker"] for w in watch]))
        mk = dict(zip(held + [w["ticker"] for w in watch], markets))

        holdings, value = [], 0.0
        for h in hs["holdings"]:
            m = mk[h["ticker"]]
            rec = E.recommend_holding(h, self.store.tracking(h["ticker"]), m)
            row = {**h, "market": m, "recommendation": rec}
            if "error" not in m:
                # En euros, con el cambio de hoy: lo que de verdad ganas o pierdes (antes solo se miraba en USD)
                row["value_eur"] = round(h["approx_shares"] * m["price"] / m["rate"], 2)
                row["pl_eur"] = round(row["value_eur"] - h["invested_eur"], 2)
                row["pl_pct"] = round(row["pl_eur"] / h["invested_eur"] * 100, 2) if h["invested_eur"] else None
                value += row["value_eur"]
            else:
                value += h["invested_eur"]
            holdings.append(row)
        watchlist = [{**w, "market": mk[w["ticker"]], "recommendation": E.recommend_watchlist(w, mk[w["ticker"]], free)}
                     for w in watch]
        sold = [{**s, "realized_pl_eur": round(self._proceeds(s) - s.get("invested_eur", 0), 2)} for s in hs["sold"]]
        realized = sum(s["realized_pl_eur"] for s in sold)
        open_ = any(m.get("market_state") == "open" for m in markets)
        return {"holdings": holdings, "watchlist": watchlist, "sold": sold[::-1],
                "cash_eur": round(hs.get("cash_eur", 0), 2), "value_eur": round(value, 2),
                "invested_eur": round(sum(h["invested_eur"] for h in hs["holdings"]), 2),
                "realized_pl_eur": round(realized, 2), "max_positions": self.max_positions,
                "positions_free": free, "market_open": open_, "broker": self.opts.get("broker") or ""}

    @staticmethod
    def _proceeds(s: dict) -> float:
        if s.get("sale_price_eur") and s.get("approx_shares"):
            return s["approx_shares"] * s["sale_price_eur"]
        pl = s.get("realized_pl_pct")
        return s.get("invested_eur", 0) * (1 + pl / 100) if pl is not None else s.get("invested_eur", 0)

    async def set_cash(self, value) -> dict:
        async with self.lock:
            hs = self.store.holdings()
            hs["cash_eur"] = round(_num(value, "el efectivo"), 2)
            hs["updated"] = now_iso()
            self.store.write("holdings.json", hs)
        return {"cash_eur": hs["cash_eur"]}

    async def add_watch(self, ticker: str, low=None, high=None, notes: str = "") -> dict:
        t = ticker_of(ticker)
        async with self.lock:
            hs, ws = self.store.holdings(), self.store.watchlist()
            if t in {h["ticker"] for h in hs["holdings"]}:
                raise StocksError(f"{t} ya está en cartera")
            if t in {w["ticker"] for w in ws["watchlist"]}:
                raise StocksError(f"{t} ya está en seguimiento")
            m = await self.market(t)
            if "error" in m:
                raise StocksError(f"«{t}» no parece un ticker válido ({m['error']})")
            entry = {"ticker": t, "name": m["name"], "current_price": m["price"], "notes": (notes or "").strip()[:500],
                     "added": now_iso()}
            if low not in (None, "") and high not in (None, ""):
                # La zona se escribe en euros y se guarda en la moneda del valor (como todo lo demás)
                lo, hi = _num(low, "la zona") * m["rate"], _num(high, "la zona") * m["rate"]
                entry.update(entry_zone=sorted([round(lo, 2), round(hi, 2)]), zone_source="manual")
            elif zone := E.auto_zone(m):
                entry.update(entry_zone=zone, zone_source="auto (SMA200-SMA50)")
            ws["watchlist"].append(entry)
            ws["updated"] = entry["added"]
            self.store.write("watchlist.json", ws)
        return entry

    async def remove_watch(self, ticker: str) -> None:
        t = ticker_of(ticker)
        async with self.lock:
            ws = self.store.watchlist()
            keep = [w for w in ws["watchlist"] if w["ticker"] != t]
            if len(keep) == len(ws["watchlist"]):
                raise StocksError(f"{t} no estaba en seguimiento")
            ws["watchlist"] = keep
            ws["removed"].append({"ticker": t, "reason": "Quitado desde el panel", "removed": now_iso()})
            self.store.write("watchlist.json", ws)

    async def buy(self, ticker: str, invested_eur) -> dict:
        """Apunta una compra que ya has hecho en tu bróker: aquí no se ejecuta ninguna orden."""
        t, amount = ticker_of(ticker), _num(invested_eur, "lo invertido")
        if amount <= 0:
            raise StocksError("lo invertido tiene que ser mayor que 0")
        async with self.lock:
            hs, ws = self.store.holdings(), self.store.watchlist()
            w = next((x for x in ws["watchlist"] if x["ticker"] == t), None)
            if not w:
                raise StocksError(f"{t} no está en seguimiento")
            if len(hs["holdings"]) >= self.max_positions:
                raise StocksError(f"ya tienes {self.max_positions} posiciones: vende algo antes de comprar {t}")
            m = await self.market(t)
            if "error" in m:
                raise StocksError(m["error"])
            at = now_iso()
            h = {"ticker": t, "name": w.get("name") or m["name"], "exchange": m["exchange"],
                 "invested_eur": round(amount, 2), "approx_shares": round(amount * m["rate"] / m["price"], 4),
                 "approx_entry_price_eur": m["price_eur"], "approx_entry_price_usd": m["price"],
                 "currency": m["currency"], "usd_eur_rate": round(m["rate"], 4), "type": "buy", "bought_at": at,
                 "thesis": w.get("notes") or f"Comprado desde seguimiento ({w.get('zone_source') or 'sin zona'})."}
            hs["holdings"].append(h)
            hs["total_invested_eur"] = round(sum(x["invested_eur"] for x in hs["holdings"]), 2)
            hs["cash_eur"] = round(hs.get("cash_eur", 0) - amount - self.commission(), 2)  # la comisión también sale
            hs["estimated_commissions_eur"] = round(hs.get("estimated_commissions_eur", 0) + self.commission(), 2)
            hs["updated"] = at
            self.store.write("holdings.json", hs)
            ws["watchlist"] = [x for x in ws["watchlist"] if x["ticker"] != t]
            ws["removed"].append({"ticker": t, "reason": f"Comprado: pasó a cartera ({amount} €)", "removed": at})
            self.store.write("watchlist.json", ws)
        return h

    async def sell(self, ticker: str) -> dict:
        """Cierra la posición entera y la guarda en el historial con lo ganado o perdido (en euros)."""
        t = ticker_of(ticker)
        async with self.lock:
            hs = self.store.holdings()
            h = next((x for x in hs["holdings"] if x["ticker"] == t), None)
            if not h:
                raise StocksError(f"{t} no está en cartera")
            m = await self.market(t)
            sale = {**h, "sold_at": now_iso()}
            if "error" not in m:
                entry = h.get("approx_entry_price_usd")
                sale.update(sale_price_usd=m["price"], sale_price_eur=m["price_eur"],
                            realized_pl_pct=round((m["price"] - entry) / entry * 100, 2) if entry else None)
                proceeds = h["approx_shares"] * m["price_eur"]
                sale["realized_pl_eur"] = round(proceeds - h["invested_eur"], 2)
            else:
                proceeds = h["invested_eur"]  # sin precio, al menos no se pierde el dinero de vista
            hs["holdings"] = [x for x in hs["holdings"] if x["ticker"] != t]
            hs["sold"].append(sale)
            hs["total_invested_eur"] = round(sum(x["invested_eur"] for x in hs["holdings"]), 2)
            hs["cash_eur"] = round(hs.get("cash_eur", 0) + proceeds - self.commission(), 2)
            hs["estimated_commissions_eur"] = round(hs.get("estimated_commissions_eur", 0) + self.commission(), 2)
            hs["updated"] = sale["sold_at"]
            self.store.write("holdings.json", hs)
        return sale

    # ---------- Descubrir ----------

    async def discover(self, limit: int = 10) -> dict:
        hs, ws = self.store.holdings(), self.store.watchlist()
        skip = {h["ticker"] for h in hs["holdings"]} | {w["ticker"] for w in ws["watchlist"]}
        pool = [t for t in E.DISCOVERY_POOL if t not in skip]
        markets = dict(zip(pool, await asyncio.gather(*(self.market(t) for t in pool))))
        # Los fundamentales (la llamada lenta) solo de los que están dentro de su zona: son los únicos que los usan
        in_zone = [t for t, m in markets.items() if "error" not in m and (z := E.auto_zone(m)) and z[0] <= m["price"] <= z[1]]
        vals = dict(zip(in_zone, await asyncio.gather(*(E.valuation(self.y, t) for t in in_zone))))
        picks = []
        for t, m in markets.items():
            rec = E.discover_verdict(m, vals.get(t))
            if rec.get("candidate"):
                picks.append({"ticker": t, "name": E.DISCOVERY_POOL[t], "market": m, "recommendation": rec,
                              "score": E.discover_score(m, rec)})
        picks.sort(key=lambda p: p["score"], reverse=True)
        return {"picks": picks[:max(1, min(20, limit))], "scanned": len(pool), "total_candidates": len(picks)}

    # ---------- Gráficas ----------

    async def series(self, t: str, range_: str) -> tuple[list[int], list[float], dict]:
        period, interval, last_day = RANGES[range_]
        d = await self.y.chart(t, period, interval)
        ts, cs = d["t"], d["c"]
        if last_day and ts:
            off = d["meta"].get("gmtoffset") or 0
            day = (ts[-1] + off) // 86400  # la última sesión, en la hora de ese mercado
            keep = [i for i, x in enumerate(ts) if (x + off) // 86400 == day]
            ts, cs = [ts[i] for i in keep], [cs[i] for i in keep]
        return ts, cs, d["meta"]

    async def charts(self, tickers: list[str], range_: str) -> dict:
        async def one(t):
            try:
                ts, cs, meta = await self.series(t, range_)
                rate = await self.y.eur_rate(meta.get("currency") or "USD")
            except YahooError:
                return t, {"labels": [], "prices": []}
            return t, {"labels": [_iso(x) for x in ts], "prices": [round(c / rate, 4) for c in cs]}
        return dict(await asyncio.gather(*(one(t) for t in tickers)))

    async def history(self, range_: str) -> dict:
        """Lo que valían tus posiciones actuales a lo largo del rango, en euros (con el cambio de cada momento)."""
        hs = self.store.holdings()["holdings"]
        lines = []
        for h in hs:
            try:
                ts, cs, meta = await self.series(h["ticker"], range_)
            except YahooError:
                continue
            cur = meta.get("currency") or "USD"
            if cur != "EUR" and ts:
                try:
                    fts, fcs, _ = await self.series(f"EUR{cur}=X", range_)
                except YahooError:
                    fts, fcs = [], []
                if fts:
                    cs = [c / fcs[_nearest(fts, x)] for x, c in zip(ts, cs)]
                else:
                    rate = await self.y.eur_rate(cur)
                    cs = [c / rate for c in cs]
            if ts:
                lines.append((ts, [c * h["approx_shares"] for c in cs]))
        if not lines:
            return {"labels": [], "values_eur": [], "buy_dates": []}
        stamps = sorted({x for ts, _ in lines for x in ts})
        total = [0.0] * len(stamps)
        for ts, vs in lines:  # cada valor arrastra su último precio donde no tiene vela (y el primero al inicio)
            j = 0
            for i, s in enumerate(stamps):
                while j + 1 < len(ts) and ts[j + 1] <= s:
                    j += 1
                total[i] += vs[j]
        return {"labels": [_iso(s) for s in stamps], "values_eur": [round(v, 2) for v in total],
                "buy_dates": [h["bought_at"] for h in hs if h.get("bought_at")]}

    # ---------- Avisos ----------

    async def _telegram(self, method: str, **kw) -> None:
        r = await self.http.post(f"https://api.telegram.org/bot{self.token}/{method}", **kw)
        if r.status_code != 200:
            raise RuntimeError(f"Telegram {method}: HTTP {r.status_code} {r.text[:200]}")

    async def notify(self, caption: str, ticker: str | None = None, zone=None, entry=None) -> None:
        """Mensaje a Telegram, con la gráfica del último mes si se puede. Sin Telegram configurado no hace nada."""
        chat = str(self.opts.get("telegram_chat") or "").strip()
        if not (self.token and chat):
            return
        png = None
        if ticker:
            try:
                _, cs, meta = await self.series(ticker, "mes")
                png = await asyncio.to_thread(price_chart, cs, zone, entry)
            except Exception as e:  # noqa: BLE001 — sin gráfica se manda el texto igual
                log.warning("gráfica de %s: %s", ticker, e)
        if png:
            try:
                await self._telegram("sendPhoto", data={"chat_id": chat, "caption": caption[:1000], "parse_mode": "HTML"},
                                     files={"photo": ("chart.png", png, "image/png")})
                return
            except Exception as e:  # noqa: BLE001
                log.warning("foto a Telegram: %s", e)
        await self._telegram("sendMessage", json={"chat_id": chat, "text": caption, "parse_mode": "HTML"})

    @staticmethod
    def caption(t: str, rec: dict, m: dict) -> str:
        lines = [f"{CONF_EMOJI.get(rec['confidence'], '⚪')} <b>{t}</b> — {rec['verdict']} ({rec['confidence']})",
                 _esc(rec["reason"]), f"Precio: {E.eur(m['price'], m['rate'])}"]
        e = m.get("earnings")
        if e and 0 <= e["days_until"] <= 10:
            lines.append(f"📅 Resultados en {e['days_until']} días ({e['date']})")
        return "\n".join(lines)

    async def _verdicts(self):
        """(clave, ticker, recomendación, mercado, zona, precio de compra) de cada posición y cada seguido."""
        hs, ws = self.store.holdings(), self.store.watchlist()
        held = {h["ticker"] for h in hs["holdings"]}
        free = len(held) < self.max_positions
        for h in hs["holdings"]:
            m = await self.market(h["ticker"])
            yield f"holding:{h['ticker']}", h["ticker"], E.recommend_holding(h, self.store.tracking(h["ticker"]), m), \
                m, None, h.get("approx_entry_price_usd")
        for w in ws["watchlist"]:
            if w["ticker"] not in held:
                m = await self.market(w["ticker"])
                yield f"watch:{w['ticker']}", w["ticker"], E.recommend_watchlist(w, m, free), m, w.get("entry_zone"), None

    async def check_changes(self) -> list[tuple[str, str]]:
        """Avisa solo cuando cambia el veredicto de algo desde la última vez. Devuelve los avisos para el push."""
        state, notes = self.store.read("alerts.json", {}), []
        async for key, t, rec, m, zone, entry in self._verdicts():
            if "error" in m:
                continue
            prev = state.get(key)
            if prev is not None and prev != rec["verdict"]:
                notes.append((f"{t}: {rec['verdict']} — {rec['reason']}", "/#stocks"))
                try:
                    await self.notify(self.caption(t, rec, m), t, zone, entry)
                except Exception as e:  # noqa: BLE001
                    log.warning("aviso de %s: %s", t, e)
            state[key] = rec["verdict"]
        self.store.write("alerts.json", state)
        return notes

    async def digest(self) -> int:
        """El resumen diario: una foto por valor, cambie o no (por si un día no abres el panel)."""
        n = 0
        async for _, t, rec, m, zone, entry in self._verdicts():
            await self.notify(self.caption(t, rec, m) if "error" not in m else f"⚪ {t}: sin datos", t, zone, entry)
            n += 1
        return n

    async def tick(self, n: int, now: float) -> list:
        """Lo llama el monitor cada 30 s."""
        notes = []
        every = max(5, self.opts.get("alert_every") or 30) * 2  # en vueltas de 30 s
        if self.opts.get("alerts", True) and n % every == 0:
            notes += await self.check_changes()
        at = self.opts.get("digest_at")
        local = datetime.fromtimestamp(now, self.tz)
        if due_daily(local, at, self._digest_day or self.store.read("digest.json", {}).get("day")):
            self._digest_day = local.strftime("%Y-%m-%d")
            self.store.write("digest.json", {"day": self._digest_day})
            await self.digest()
        return notes


def _nearest(ts: list[int], x: int) -> int:
    i = bisect.bisect_left(ts, x)
    if i == 0:
        return 0
    if i >= len(ts):
        return len(ts) - 1
    return i if ts[i] - x < x - ts[i - 1] else i - 1


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
