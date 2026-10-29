from fastapi import APIRouter, Depends, HTTPException, Request

from ... import auth
from ...core import json_body
from ...secrets import load_secrets
from .portfolio import RANGES, Stocks, StocksError, ticker_of


def setup(ctx) -> APIRouter:
    st = Stocks(ctx.cfg.mod("stocks"), ctx.cfg.data_dir, load_secrets(ctx.cfg.data_dir).get("stocks", {}), tz=ctx.tz)
    ctx.hooks.append(st)
    ctx.stocks = st
    r = APIRouter(prefix="/api/stocks", dependencies=[Depends(auth.require_auth)])

    async def run(coro):
        try:
            return await coro
        except StocksError as e:
            raise HTTPException(400, str(e))

    def rng(range: str) -> str:
        if range not in RANGES:
            raise HTTPException(400, f"range tiene que ser uno de {', '.join(RANGES)}")
        return range

    @r.get("")
    async def portfolio():
        return await st.portfolio()

    @r.get("/discover")
    async def discover(limit: int = 10):
        return await st.discover(limit)

    @r.get("/chart")
    async def chart(tickers: str, range: str = "anio"):
        try:
            ts = [ticker_of(t) for t in tickers.split(",") if t.strip()][:30]
        except StocksError as e:
            raise HTTPException(400, str(e))
        return await st.charts(ts, rng(range))

    @r.get("/history")
    async def history(range: str = "anio"):
        return await st.history(rng(range))

    @r.post("/watchlist")
    async def add(request: Request):
        b = await json_body(request)
        return await run(st.add_watch(str(b.get("ticker", "")), b.get("entry_low"), b.get("entry_high"),
                                      str(b.get("notes") or "")))

    @r.delete("/watchlist/{ticker}")
    async def remove(ticker: str):
        await run(st.remove_watch(ticker))
        return {"ok": True}

    @r.post("/watchlist/{ticker}/buy")
    async def buy(ticker: str, request: Request):
        return await run(st.buy(ticker, (await json_body(request)).get("invested_eur")))

    @r.post("/holdings/{ticker}/sell")
    async def sell(ticker: str):
        return await run(st.sell(ticker))

    @r.put("/cash")
    async def cash(request: Request):
        return await run(st.set_cash((await json_body(request)).get("cash_eur")))

    @r.post("/digest")
    async def digest():
        if not (st.token and str(st.opts.get("telegram_chat") or "").strip()):
            raise HTTPException(400, "configura Telegram (token y chat) en Módulos → Bolsa")
        return {"sent": await st.digest()}

    return r
