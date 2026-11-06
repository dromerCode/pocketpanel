"""Lo que el panel hace (o deja de hacer) en segundo plano: que no gaste ni acumule sin necesidad."""
import asyncio

import app.modules.stocks.yahoo as yahoo
from app.docker_api import DockerClient
from app.jobs import Job


class FakeSession:
    opened = 0

    def __init__(self, cookies=None):
        FakeSession.opened += 1
        self.cookies, self.closed = cookies or {"crumb-cookie": 1}, False

    async def get(self, url, **kw):
        await asyncio.sleep(0.01)
        return url

    async def close(self):
        self.closed = True


def test_idle_session_closes_and_keeps_cookies(monkeypatch):
    monkeypatch.setattr(yahoo, "IDLE", 0.05)

    async def main():
        s = yahoo.IdleSession(FakeSession)
        assert await s.get("a") == "a"
        first = s.s
        await asyncio.sleep(0.1)                     # un rato sin pedir nada: se cierra (y su temporizador con ella)
        assert s.s is None and first.closed
        await s.get("b")                             # se vuelve a abrir con las mismas cookies
        assert s.s.cookies is first.cookies
        await s.close()
    asyncio.run(main())


def test_idle_session_stays_open_while_busy(monkeypatch):
    monkeypatch.setattr(yahoo, "IDLE", 0.02)

    async def main():
        FakeSession.opened = 0
        s = yahoo.IdleSession(FakeSession)
        for _ in range(5):
            await asyncio.gather(s.get("x"), s.get("y"))
        assert FakeSession.opened == 1
        await s.close()
    asyncio.run(main())


def test_concurrent_requests_ask_yahoo_once():
    async def main():
        y = yahoo.Yahoo(session=object())
        calls = 0

        async def compute():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            return calls
        assert await asyncio.gather(*(y.cached("k", 300, compute) for _ in range(4))) == [1, 1, 1, 1]
        assert calls == 1 and not y._inflight
    asyncio.run(main())


def test_failed_request_is_shared_and_not_cached():
    async def main():
        y = yahoo.Yahoo(session=object())

        async def bad():
            await asyncio.sleep(0.01)
            raise yahoo.YahooError("429")
        r = await asyncio.gather(*(y.cached("k", 300, bad) for _ in range(3)), return_exceptions=True)
        assert all(isinstance(x, yahoo.YahooError) for x in r) and "k" not in y._cache
    asyncio.run(main())


def test_request_survives_whoever_asked_leaving():
    """Si se cierra la pantalla que lo pidió, la petición a Yahoo termina igual y queda guardada para la siguiente."""
    async def main():
        y = yahoo.Yahoo(session=object())
        calls = 0

        async def compute():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            return "ok"
        t = asyncio.create_task(y.cached("k", 300, compute))
        await asyncio.sleep(0.005)
        t.cancel()
        await asyncio.sleep(0.03)
        assert t.cancelled() and not y._inflight
        assert await y.cached("k", 300, compute) == "ok" and calls == 1
    asyncio.run(main())


def test_docker_stats_forget_removed_containers():
    async def main():
        d = DockerClient("/nonexistent.sock")

        async def one(cid):
            d._prev[cid] = {"cpu_stats": {}}
            return cid, {}
        d._stats_one = one
        await d.stats(["a", "b"])
        await d.stats(["b", "c"])                    # «a» se recreó con otro id al actualizarlo
        assert set(d._prev) == {"b", "c"}
    asyncio.run(main())


def test_job_log_is_bounded():
    j = Job("copiar")
    for i in range(5000):
        j.log(f"línea {i}")
    assert len(j.lines) <= 2000 and j.lines[-1].endswith("línea 4999")
