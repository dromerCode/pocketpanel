"""Yahoo Finance sin yfinance: las mismas llamadas que hace yfinance, pero sin pandas ni numpy.

Va con curl_cffi haciéndose pasar por Chrome: con curl o httpx a pelo Yahoo da datos con horas de retraso y
corta con 429 enseguida. Las valoraciones (quoteSummary) necesitan además la cookie y el «crumb»."""
import asyncio
import time

Q = "https://query2.finance.yahoo.com"
TTL = 300  # los precios se refrescan cada 5 min: no hace falta más y Yahoo lo agradece
IDLE = 60  # s sin pedir nada a Yahoo: se cierra la conexión (ver IdleSession)


class YahooError(Exception):
    pass


class IdleSession:
    """La sesión de curl_cffi, abierta solo mientras se usa.

    Mientras está abierta, curl_cffi despierta el panel 10 veces por segundo (un temporizador suyo que no para nunca),
    y con la Bolsa activa eso era casi todo lo que gastaba el panel en reposo. Así se abre al pedir algo y se cierra
    al minuto sin uso; las cookies (y con ellas el «crumb» de Yahoo) pasan a la siguiente."""

    def __init__(self, factory):
        self.factory = factory
        self.s, self.cookies, self.busy, self.timer = None, None, 0, None
        self._closing: set = set()

    async def get(self, *args, **kwargs):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if self.s is None:
            self.s = self.factory(**({"cookies": self.cookies} if self.cookies else {}))
        self.busy += 1
        try:
            return await self.s.get(*args, **kwargs)
        finally:
            self.busy -= 1
            if not self.busy and self.s is not None:
                self.timer = asyncio.get_running_loop().call_later(IDLE, self._expire)

    def _expire(self) -> None:
        self.timer = None
        if self.busy or self.s is None:
            return
        s, self.s = self.s, None
        self.cookies = s.cookies
        t = asyncio.get_running_loop().create_task(s.close())
        self._closing.add(t)
        t.add_done_callback(self._closing.discard)

    async def close(self) -> None:
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if self.s is not None:
            s, self.s = self.s, None
            await s.close()


class Yahoo:
    def __init__(self, session=None, parallel: int = 4):
        if session is None:
            from curl_cffi.requests import AsyncSession  # dependencia del módulo (requirements.txt), no del núcleo
            session = IdleSession(lambda **kw: AsyncSession(impersonate="chrome", timeout=20, **kw))
        self.s = session
        self.sem = asyncio.Semaphore(parallel)
        self.crumb: str | None = None
        self._crumb_lock = asyncio.Lock()
        self._cache: dict[str, tuple[float, object]] = {}
        self._inflight: dict[str, asyncio.Future] = {}

    async def cached(self, key: str, ttl: float, compute):
        """Lo guardado si tiene menos de `ttl` s. Si ya se está pidiendo (dos pantallas, o el widget y la vista a la
        vez), se espera a esa misma respuesta en vez de volver a preguntar a Yahoo."""
        now = time.time()
        hit = self._cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        while key in self._inflight:
            f = self._inflight[key]
            await asyncio.wait({f})  # sin cancelarla aunque esta petición se vaya
            if not f.cancelled():
                return f.result()
        fut = self._inflight[key] = asyncio.get_running_loop().create_future()
        try:
            value = await compute()
        except asyncio.CancelledError:  # quien la pidió se fue: los que esperaban, que pregunten ellos
            fut.cancel()
            raise
        except Exception as e:
            fut.set_exception(e)
            fut.exception()  # que no avise de «excepción sin recoger» si nadie más la esperaba
            raise
        finally:
            del self._inflight[key]
        fut.set_result(value)
        if len(self._cache) > 500:  # lo caducado hace más de un día ya no sirve (valores que ya no miras…)
            self._cache = {k: v for k, v in self._cache.items() if now - v[0] < 86400}
        self._cache[key] = (time.time(), value)
        return value

    async def _get(self, url: str, params: dict) -> dict:
        async with self.sem:
            r = await self.s.get(url, params=params)
        if r.status_code == 404:
            raise YahooError("no existe")
        if r.status_code == 429:
            raise YahooError("Yahoo pide esperar (429)")
        try:
            return r.json()
        except ValueError:
            raise YahooError(f"respuesta rara de Yahoo (HTTP {r.status_code})") from None

    async def chart(self, ticker: str, range_: str, interval: str, ttl: float = TTL) -> dict:
        """Velas y datos básicos: {"meta": {...}, "t": [epoch], "o"/"h"/"l"/"c": [...]} sin huecos de cierre."""
        async def compute():
            j = await self._get(f"{Q}/v8/finance/chart/{ticker}", {"range": range_, "interval": interval})
            res = (j.get("chart") or {}).get("result")
            if not res:
                err = ((j.get("chart") or {}).get("error") or {}).get("description")
                raise YahooError(err or "sin datos")
            res = res[0]
            ind = res.get("indicators", {})
            q = (ind.get("quote") or [{}])[0]
            closes = q.get("close") or []
            # Precios ajustados por dividendos (como yfinance): el día que se paga uno no es una caída de verdad
            adj = (ind.get("adjclose") or [{}])[0].get("adjclose") or closes
            rows = []
            for t, o, h, l, c, a in zip(res.get("timestamp") or [], q.get("open") or [], q.get("high") or [],
                                        q.get("low") or [], closes, adj):
                if c is None:  # Yahoo cuela velas vacías (sesión sin publicar): envenenan las medias
                    continue
                k = a / c if a and c else 1
                rows.append((t, o and o * k, h and h * k, l and l * k, c * k))
            t, o, h, l, c = (list(x) for x in zip(*rows)) if rows else ([], [], [], [], [])
            return {"meta": res.get("meta") or {}, "t": t, "o": o, "h": h, "l": l, "c": c}
        return await self.cached(f"chart:{ticker}:{range_}:{interval}", ttl, compute)

    async def _crumb(self, renew: bool = False) -> str:
        async with self._crumb_lock:
            if self.crumb and not renew:
                return self.crumb
            await self.s.get("https://fc.yahoo.com", allow_redirects=True)  # deja la cookie
            r = await self.s.get("https://query1.finance.yahoo.com/v1/test/getcrumb")
            if r.status_code != 200 or not r.text or "<" in r.text:
                raise YahooError(f"Yahoo no da acceso a los fundamentales (HTTP {r.status_code})")
            self.crumb = r.text.strip()
            return self.crumb

    async def summary(self, ticker: str, modules: str, ttl: float) -> dict:
        async def compute():
            for renew in (False, True):
                crumb = await self._crumb(renew)
                j = await self._get(f"{Q}/v10/finance/quoteSummary/{ticker}", {"modules": modules, "crumb": crumb})
                res = (j.get("quoteSummary") or {}).get("result")
                if res:
                    return res[0]
                err = ((j.get("quoteSummary") or {}).get("error") or {}).get("code", "")
                if "Unauthorized" not in str(err) and "Invalid Crumb" not in str(j):
                    break
            raise YahooError("sin fundamentales")
        return await self.cached(f"summary:{ticker}:{modules}", ttl, compute)

    async def eur_rate(self, currency: str) -> float:
        """Unidades de `currency` por 1 €."""
        if not currency or currency == "EUR":
            return 1.0
        d = await self.chart(f"EUR{currency}=X", "5d", "1d")
        rate = d["meta"].get("regularMarketPrice") or (d["c"][-1] if d["c"] else None)
        if not rate:
            raise YahooError(f"sin cambio EUR/{currency}")
        return float(rate)

    async def close(self) -> None:
        await self.s.close()


def raw(d: dict | None, key: str):
    """Los números de quoteSummary vienen como {"raw": 1.07, "fmt": "1.07"}."""
    v = (d or {}).get(key)
    return v.get("raw") if isinstance(v, dict) else v
