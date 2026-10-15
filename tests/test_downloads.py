import httpx
import pytest

from app.downloads import Arr, DownloadsError, DownloadsWatcher, QBit

H1 = "a" * 40


def qbit_handler(v5=True, user_ok=True, log=None):
    def h(r):
        p = r.url.path
        if log is not None:
            log.append(p)
        if p == "/api/v2/auth/login":
            ok = b"username=admin" in r.content and user_ok
            return httpx.Response(200, text="Ok." if ok else "Fails.",
                                  headers={"set-cookie": "SID=abc; path=/"} if ok else {})
        if "SID=abc" not in r.headers.get("cookie", ""):
            return httpx.Response(403)
        if p == "/api/v2/torrents/info":
            return httpx.Response(200, json=[
                {"hash": H1, "name": "Dune.2024.1080p", "progress": 0.5, "state": "downloading", "dlspeed": 2_000_000,
                 "upspeed": 1000, "eta": 600, "size": 4_000_000_000},
                {"hash": "b" * 40, "name": "Ubuntu.iso", "progress": 1.0, "state": "stoppedUP" if v5 else "pausedUP",
                 "dlspeed": 0, "upspeed": 0, "eta": 8640000, "size": 5_000_000_000}])
        if p == "/api/v2/transfer/info":
            return httpx.Response(200, json={"dl_info_speed": 2_000_000, "up_info_speed": 1000})
        if p in ("/api/v2/torrents/stop", "/api/v2/torrents/start"):
            return httpx.Response(200 if v5 else 404)
        if p in ("/api/v2/torrents/pause", "/api/v2/torrents/resume"):
            return httpx.Response(404 if v5 else 200)
        return httpx.Response(404)
    return h


def qb(**kw):
    log = []
    return QBit("http://qb", "admin", "pw", http=httpx.AsyncClient(transport=httpx.MockTransport(qbit_handler(log=log, **kw)))), log


async def test_qbit_lists_torrents_normalized():
    q, _ = qb()
    ts = await q.torrents()
    assert ts[0] == {"hash": H1, "name": "Dune.2024.1080p", "progress": 0.5, "state": "downloading", "paused": False,
                     "done": False, "dl": 2_000_000, "up": 1000, "eta": 600, "size": 4_000_000_000}
    assert ts[1]["paused"] is True and ts[1]["done"] is True and ts[1]["eta"] is None
    assert await q.transfer() == {"dl": 2_000_000, "up": 1000}


@pytest.mark.parametrize("v5,path", [(True, "/api/v2/torrents/stop"), (False, "/api/v2/torrents/pause")])
async def test_pause_works_on_v4_and_v5(v5, path):
    q, log = qb(v5=v5)
    await q.set_paused(H1, True)
    assert log[-1] == path
    assert (await q.torrents())[1]["paused"] is True


async def test_bad_login():
    q, _ = qb(user_ok=False)
    with pytest.raises(DownloadsError, match="usuario"):
        await q.torrents()


def arr_handler(kind):
    def h(r):
        if r.headers.get("x-api-key") != "k":
            return httpx.Response(401)
        p = r.url.path
        if p == "/api/v3/queue":
            if kind == "sonarr":
                rec = {"title": "release.name", "status": "downloading", "size": 100, "sizeleft": 25, "timeleft": "00:10:00",
                       "series": {"title": "Severance"}, "episode": {"seasonNumber": 2, "episodeNumber": 3}}
            else:
                rec = {"title": "release.name", "status": "queued", "size": 0, "sizeleft": 0, "movie": {"title": "Dune"}}
            return httpx.Response(200, json={"records": [rec]})
        if p == "/api/v3/calendar":
            if kind == "sonarr":
                return httpx.Response(200, json=[{"series": {"title": "Severance"}, "seasonNumber": 2, "episodeNumber": 4,
                                                  "title": "Woe's Hollow", "airDateUtc": "2026-10-17T02:00:00Z",
                                                  "hasFile": False}])
            return httpx.Response(200, json=[{"title": "Dune: Part Three", "digitalRelease": "2026-10-20T00:00:00Z",
                                              "inCinemas": "2026-09-01T00:00:00Z", "hasFile": False}])
        if p == "/api/v3/health":
            return httpx.Response(200, json=[{"source": "IndexerCheck", "type": "warning", "message": "Indexers caídos"}])
        return httpx.Response(404)
    return h


def arr(kind, key="k"):
    return Arr(kind, "http://arr", key, http=httpx.AsyncClient(transport=httpx.MockTransport(arr_handler(kind))))


async def test_sonarr_queue_and_calendar():
    a = arr("sonarr")
    assert await a.queue() == [{"title": "Severance S02E03", "status": "downloading", "progress": 0.75,
                                "timeleft": "00:10:00", "kind": "sonarr"}]
    up = await a.upcoming()
    assert up == [{"title": "Severance S02E04 · Woe's Hollow", "when": "2026-10-17T02:00:00Z", "kind": "sonarr",
                   "has_file": False}]


async def test_radarr_queue_and_calendar_picks_future_date():
    a = arr("radarr")
    q = await a.queue()
    assert q[0]["title"] == "Dune" and q[0]["progress"] is None
    up = await a.upcoming(now="2026-10-15T00:00:00Z")
    assert up[0]["title"] == "Dune: Part Three" and up[0]["when"] == "2026-10-20T00:00:00Z"


async def test_arr_bad_key():
    with pytest.raises(DownloadsError, match="API key"):
        await arr("sonarr", key="mala").queue()


class FakeQ:
    def __init__(self):
        self.progress = 0.5

    async def torrents(self):
        return [{"hash": H1, "name": "Dune", "progress": self.progress, "done": self.progress >= 1}]


class FakeArr:
    kind = "sonarr"

    def __init__(self):
        self.msgs = []

    async def health(self):
        return [{"type": "warning", "message": m} for m in self.msgs]


async def test_watcher_announces_finished_and_new_health_problems():
    q, a = FakeQ(), FakeArr()
    w = DownloadsWatcher(q, [a], notify_finished=True)
    assert await w.tick(0, 0) == []
    q.progress = 1.0
    assert await w.tick(2, 0) == [("Descargado: Dune", "/#downloads")]
    assert await w.tick(4, 0) == []
    a.msgs = ["Indexers caídos"]
    assert await w.tick(10, 0) == [("Sonarr: Indexers caídos", "/#downloads")]
    assert await w.tick(20, 0) == []


async def test_watcher_can_be_quiet_about_finished():
    q = FakeQ()
    w = DownloadsWatcher(q, [], notify_finished=False)
    await w.tick(0, 0)
    q.progress = 1.0
    assert await w.tick(2, 0) == []


async def test_watcher_one_service_down_does_not_hide_others():
    class Broken:
        kind = "sonarr"

        async def health(self):
            raise DownloadsError("Sonarr no responde")

    class BrokenQ:
        async def torrents(self):
            raise DownloadsError("qBittorrent no responde")

    good = FakeArr()
    good.kind = "radarr"
    w = DownloadsWatcher(BrokenQ(), [Broken(), good], notify_finished=True)
    await w.tick(0, 0)
    good.msgs = ["Disco lleno"]
    assert await w.tick(10, 0) == [("Radarr: Disco lleno", "/#downloads")]
