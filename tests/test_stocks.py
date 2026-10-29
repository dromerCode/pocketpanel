"""Módulo de bolsa: indicadores, reglas, cartera (compras, ventas, efectivo) y avisos, con un Yahoo de mentira."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import load_config
from app.main import create_app
from app.modules.stocks import engine as E
from app.modules.stocks import indicators as I
from app.modules.stocks import portfolio as P
from app.modules.stocks.pngchart import price_chart
from app.modules.stocks.yahoo import Yahoo, YahooError
from tests.test_modules import ReadyDeps

DAY = 86400


class NoNet:
    async def get(self, *a, **kw):
        raise OSError("sin red en los tests")


class FakeYahoo(Yahoo):
    """Series inventadas: `prices[ticker]` es la lista de cierres diarios (la última es el precio de ahora)."""
    def __init__(self, prices, currency=None, rate=1.10):
        super().__init__(session=NoNet())
        self.prices, self.currency, self.rate = prices, currency or {}, rate

    async def chart(self, ticker, range_, interval, ttl=0):
        if ticker.startswith("EUR"):
            cs = [self.rate] * 30
        elif ticker not in self.prices:
            raise YahooError("no existe")
        else:
            cs = self.prices[ticker]
        t0 = 1_700_000_000
        return {"meta": {"currency": self.currency.get(ticker, "USD"), "regularMarketPrice": cs[-1],
                         "shortName": f"{ticker} Inc.", "fullExchangeName": "NasdaqGS"},
                "t": [t0 + i * DAY for i in range(len(cs))], "o": cs, "h": [c * 1.01 for c in cs],
                "l": [c * 0.99 for c in cs], "c": cs}

    async def summary(self, ticker, modules, ttl):
        if "calendarEvents" in modules:
            return {"calendarEvents": {"earnings": {"earningsDate": []}}}
        return {"financialData": {"recommendationKey": "buy", "targetMeanPrice": {"raw": 200}},
                "defaultKeyStatistics": {"pegRatio": {"raw": 1.1}}}

    async def eur_rate(self, currency):
        return 1.0 if currency == "EUR" else self.rate


def rising(n=260, start=100.0, step=0.2):
    return [start + i * step for i in range(n)]


def falling_then(n=260):
    """Tendencia alcista larga y un retroceso fuerte al final: precio entre la media de 200 y la de 50."""
    xs = [100 + i * 0.5 for i in range(n - 15)]
    return xs + [xs[-1] - 3 * (i + 1) for i in range(15)]


# ---------- Indicadores (mismas fórmulas que pandas) ----------

def test_indicators():
    assert I.sma([1, 2, 3, 4], 2) == 3.5 and I.sma([1], 2) is None
    assert I.ema([1, 2, 3], 2) == [1, 1 + 2 / 3, (1 + 2 / 3) / 3 + 2 * 3 / 3]
    assert I.rsi(rising(30)) == 100.0
    assert I.rsi([10, 9, 8, 7]) == 0.0
    assert I.macd(rising(60)) == (True, False)       # subida constante: MACD alcista, sin cruces
    assert I.macd(rising(60) + [80.0] * 3)[1] is True  # caída brusca: cambia de signo
    assert I.bollinger_pct([1.0] * 20, 1.0) is None  # sin anchura no hay bandas
    assert round(I.bollinger_pct(list(range(20)), 9.5)) == 50
    assert I.atr([2.0] * 14, [1.0] * 14, [1.5] * 14) == 1.0


# ---------- Reglas ----------

def market(**kw):
    m = {"price": 100.0, "rate": 1.1, "rsi14": 50, "bb_pct": 50, "trend": "alcista", "sma50": 110, "sma200": 90,
         "macd_bullish": True, "atr_stop_pct": None, "change_5d_pct": 0, "market_state": "open"}
    return {**m, **kw}


def test_holding_rules():
    h = {"approx_entry_price_usd": 100.0}
    assert E.recommend_holding(h, None, market(price=80))["verdict"] == "VENDER"  # -20 % con stop manual -15 %
    assert E.recommend_holding(h, None, market(price=90, atr_stop_pct=-8))["verdict"] == "VENDER"
    assert E.recommend_holding(h, {"target": 120}, market(price=125))["verdict"] == "CONSIDERAR VENTA PARCIAL"
    spike = E.recommend_holding(h, None, market(price=110, change_5d_pct=18, rsi14=72))
    assert spike["verdict"] == "CONSIDERAR VENTA PARCIAL" and spike["confidence"] == "ALTA"
    assert E.recommend_holding(h, None, market(trend="bajista", rsi14=35, macd_bullish=False))["verdict"] == "VIGILAR"
    assert E.recommend_holding(h, None, market())["verdict"] == "MANTENER"
    assert E.recommend_holding(h, None, {"error": "x"})["verdict"] == "SIN DATOS"


def test_watchlist_rules():
    w = {"entry_zone": [90, 105], "zone_source": "manual"}
    assert E.recommend_watchlist(w, market(), True)["verdict"] == "ZONA DE COMPRA"
    assert E.recommend_watchlist(w, market(rsi14=35), True)["confidence"] == "ALTA"
    assert E.recommend_watchlist(w, market(price=80), True)["verdict"] == "POR DEBAJO DE ZONA"
    assert E.recommend_watchlist(w, market(price=120), True)["verdict"] == "ESPERAR"
    assert E.recommend_watchlist(w, market(), False)["verdict"] == "CARTERA LLENA"
    assert E.recommend_watchlist({}, market(), True)["verdict"] == "SIN ZONA"


def test_discover_needs_valuation_for_buy_zone():
    m = market()  # dentro de la zona automática 90-110
    assert E.discover_verdict(m, {"rating": "buy"})["verdict"] == "ZONA DE COMPRA"
    assert E.discover_verdict(m, {"rating": "hold"})["verdict"] == "MOMENTUM ALCISTA"
    assert E.discover_verdict(market(rsi14=35), None)["verdict"] == "POSIBLE ENTRADA"
    hi = E.discover_score(m, {"verdict": "ZONA DE COMPRA", "confidence": "ALTA"})
    lo = E.discover_score(m, {"verdict": "POSIBLE ENTRADA", "confidence": "MEDIA"})
    assert hi > lo


def test_market_open_uses_yahoo_session_hours():
    meta = {"currentTradingPeriod": {"regular": {"start": 100, "end": 200}}}
    assert E.market_open(meta, 150) and not E.market_open(meta, 250) and not E.market_open({}, 150)


# ---------- Cartera ----------

def stocks(tmp_path, prices, **kw):
    return P.Stocks({"max_positions": 2, "commission": "1"}, str(tmp_path), {}, yahoo=FakeYahoo(prices, **kw))


def test_market_data_and_eur(tmp_path):
    st = stocks(tmp_path, {"AAA": rising()})
    m = asyncio.run(st.market("AAA"))
    assert m["price"] == round(rising()[-1], 2) and m["price_eur"] == round(rising()[-1] / 1.10, 2)
    assert m["trend"] == "alcista" and m["currency"] == "USD" and m["name"] == "AAA Inc."
    assert "error" in asyncio.run(st.market("NOPE"))


def test_watch_buy_sell_flow(tmp_path):
    st = stocks(tmp_path, {"AAA": rising(), "BBB": falling_then()})
    asyncio.run(st.set_cash(500))
    e = asyncio.run(st.add_watch("aaa", low=90, high=100))
    assert e["ticker"] == "AAA" and e["zone_source"] == "manual"
    assert e["entry_zone"] == [round(90 * 1.10, 2), round(100 * 1.10, 2)]  # escrita en €, guardada en USD
    auto = asyncio.run(st.add_watch("BBB"))
    assert auto["zone_source"].startswith("auto") and len(auto["entry_zone"]) == 2
    with pytest.raises(P.StocksError, match="ya está en seguimiento"):
        asyncio.run(st.add_watch("AAA"))
    with pytest.raises(P.StocksError, match="no parece un ticker"):
        asyncio.run(st.add_watch("NOPE"))
    with pytest.raises(P.StocksError, match="ticker no válido"):
        asyncio.run(st.add_watch("<script>"))

    h = asyncio.run(st.buy("AAA", 100))
    assert h["invested_eur"] == 100 and h["approx_shares"] == round(100 * 1.10 / rising()[-1], 4)
    hs = st.store.holdings()
    assert hs["cash_eur"] == 399.0  # 500 - 100 - 1 de comisión
    assert [w["ticker"] for w in st.store.watchlist()["watchlist"]] == ["BBB"]

    p = asyncio.run(st.portfolio())
    assert [x["ticker"] for x in p["holdings"]] == ["AAA"] and p["holdings"][0]["pl_eur"] == pytest.approx(0, abs=0.1)

    st.y.rate = 1.0  # el euro cae frente al dólar: misma cotización, más euros
    st.y._cache.clear()
    sale = asyncio.run(st.sell("AAA"))
    assert sale["realized_pl_pct"] == 0
    assert sale["realized_pl_eur"] == pytest.approx(10, abs=0.1)  # +10 % solo por el cambio (antes no se veía)
    hs = st.store.holdings()
    assert hs["holdings"] == [] and hs["sold"][0]["ticker"] == "AAA"
    assert hs["cash_eur"] == pytest.approx(399 + 110 - 1, abs=0.1)
    assert asyncio.run(st.portfolio())["realized_pl_eur"] == pytest.approx(10, abs=0.1)


def test_max_positions(tmp_path):
    st = stocks(tmp_path, {t: rising() for t in ("A", "B", "C")})
    for t in ("A", "B", "C"):
        asyncio.run(st.add_watch(t))
    asyncio.run(st.buy("A", 10))
    asyncio.run(st.buy("B", 10))
    with pytest.raises(P.StocksError, match="ya tienes 2 posiciones"):
        asyncio.run(st.buy("C", 10))
    assert asyncio.run(st.portfolio())["watchlist"][0]["recommendation"]["verdict"] == "CARTERA LLENA"


def test_reads_old_portfolio_files(tmp_path):
    # Los JSON del portfolio de antes, tal cual
    (tmp_path / "stocks").mkdir()
    (tmp_path / "stocks" / "holdings.json").write_text(json.dumps({"holdings": [
        {"ticker": "AAA", "invested_eur": 100, "approx_shares": 1, "approx_entry_price_usd": 110, "bought_at": "2026-01-01T00:00:00Z"}],
        "sold": [{"ticker": "OLD", "invested_eur": 100, "realized_pl_pct": 20}], "cash_eur": 5}))
    (tmp_path / "stocks" / "aaa_tracking.json").write_text(json.dumps({"target": 1}))
    p = asyncio.run(stocks(tmp_path, {"AAA": rising()}).portfolio())
    assert p["holdings"][0]["recommendation"]["verdict"] == "CONSIDERAR VENTA PARCIAL"  # objetivo del tracking
    assert p["realized_pl_eur"] == 20 and p["cash_eur"] == 5


def test_history_sums_positions_in_eur(tmp_path):
    st = stocks(tmp_path, {"AAA": [10.0] * 30, "BBB": [20.0] * 30}, rate=2.0)
    st.store.write("holdings.json", {"holdings": [{"ticker": "AAA", "approx_shares": 1, "invested_eur": 5},
                                                  {"ticker": "BBB", "approx_shares": 2, "invested_eur": 20}]})
    h = asyncio.run(st.history("mes"))
    assert set(h["values_eur"]) == {(10 + 40) / 2}
    assert h["labels"][0].endswith("Z")


# ---------- Avisos ----------

class FakeHTTP:
    def __init__(self):
        self.sent = []

    async def post(self, url, **kw):
        self.sent.append((url.rsplit("/", 1)[1], kw))

        class R:
            status_code = 200
            text = "{}"
        return R()


def test_alerts_only_on_change(tmp_path):
    http = FakeHTTP()
    st = P.Stocks({"max_positions": 3, "telegram_chat": "42"}, str(tmp_path), {"telegram_token": "T"},
                  yahoo=FakeYahoo({"AAA": rising()}), http=http)
    asyncio.run(st.add_watch("AAA", low=1, high=2))
    assert asyncio.run(st.check_changes()) == []  # la primera vez solo se apunta
    assert asyncio.run(st.check_changes()) == []
    st.store.write("alerts.json", {"watch:AAA": "ZONA DE COMPRA"})
    notes = asyncio.run(st.check_changes())
    assert len(notes) == 1 and notes[0][0].startswith("AAA: ESPERAR")
    assert http.sent[0][0] == "sendPhoto" and http.sent[0][1]["data"]["chat_id"] == "42"
    assert http.sent[0][1]["files"]["photo"][1][:4] == b"\x89PNG"


def test_no_telegram_no_messages(tmp_path):
    http = FakeHTTP()
    st = P.Stocks({}, str(tmp_path), {}, yahoo=FakeYahoo({"AAA": rising()}), http=http)
    asyncio.run(st.add_watch("AAA"))
    assert asyncio.run(st.digest()) == 1 and http.sent == []


def test_png_chart():
    png = price_chart([1, 3, 2, 4], zone=[1.5, 2.5], entry=2, w=60, h=30)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and price_chart([1]) is None


# ---------- API ----------

@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "Yahoo", lambda: FakeYahoo({"AAA": rising()}))
    p = tmp_path / "config.yml"
    p.write_text("modules: {stocks: {enabled: true}}")
    cfg = load_config(str(p), {"PANEL_PIN_HASH": auth.hash_pin("1234"), "PANEL_SECRET": "s",
                               "PANEL_DATA": str(tmp_path / "data")})
    c = TestClient(create_app(cfg, deps=ReadyDeps(cfg.data_dir)))
    assert c.post("/api/login", json={"pin": "1234"}).status_code == 200
    return c


def test_api(api):
    assert api.get("/api/stocks").json()["holdings"] == []
    assert api.post("/api/stocks/watchlist", json={"ticker": "AAA"}).status_code == 200
    assert api.post("/api/stocks/watchlist", json={"ticker": "AAA"}).status_code == 400
    assert api.post("/api/stocks/watchlist/AAA/buy", json={"invested_eur": "mucho"}).status_code == 400
    assert api.post("/api/stocks/watchlist/AAA/buy", json={"invested_eur": 50}).status_code == 200
    assert api.get("/api/stocks").json()["holdings"][0]["ticker"] == "AAA"
    assert api.get("/api/stocks/chart?tickers=AAA&range=mes").json()["AAA"]["prices"]
    assert api.get("/api/stocks/chart?tickers=AAA&range=siglo").status_code == 400
    assert api.get("/api/stocks/history?range=anio").json()["values_eur"]
    assert api.put("/api/stocks/cash", json={"cash_eur": 12.5}).json() == {"cash_eur": 12.5}
    assert api.post("/api/stocks/digest").status_code == 400  # sin Telegram
    assert api.post("/api/stocks/holdings/AAA/sell").status_code == 200
    assert api.get("/modules/stocks/index.js").status_code == 200


def test_api_needs_login(api):
    api.cookies.clear()
    assert api.get("/api/stocks").status_code == 401


# ---------- Dependencias (de verdad, sin descargar) ----------

class PendingDeps(ReadyDeps):
    def __init__(self, data_dir):
        super().__init__(data_dir)
        self.installed = []

    def ready(self, name):
        return name != "stocks" or "stocks" in self.installed

    async def install(self, name):
        self.installed.append(name)
        from app.jobs import Job
        job = self.jobs[name] = Job(name)
        job.status = "ok"
        return job


def test_module_waits_for_its_deps_then_restarts(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text("modules: {stocks: {enabled: true}}")
    cfg = load_config(str(p), {"PANEL_PIN_HASH": auth.hash_pin("1234"), "PANEL_SECRET": "s",
                               "PANEL_DATA": str(tmp_path / "data")})
    restarts, deps = [], PendingDeps(cfg.data_dir)
    app = create_app(cfg, restart=lambda: restarts.append(1), deps=deps)
    with TestClient(app) as c:  # con `with` arranca el lifespan, que es quien descarga
        assert c.post("/api/login", json={"pin": "1234"}).status_code == 200
        me = c.get("/api/me").json()
        assert "stocks" not in me["modules"] and me["deps_pending"] == ["stocks"]
        assert c.get("/api/stocks").status_code != 200
        assert c.get("/modules/stocks/index.js").status_code == 404
        view = next(m for m in c.get("/api/modules").json()["modules"] if m["name"] == "stocks")
        assert view["deps"]["packages"] == ["curl_cffi==0.16.3"]
        for _ in range(50):
            if restarts:
                break
            asyncio.run(asyncio.sleep(0.02))
        assert deps.installed == ["stocks"] and restarts == [1]
        assert c.get("/api/deps/stocks").json()["status"] == "ok"


def test_httpx_does_not_log_the_telegram_token():
    # httpx apunta en INFO la URL de cada petición, y la de Telegram lleva el token del bot
    import logging

    import app.main  # noqa: F401
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
