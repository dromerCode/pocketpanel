from app.config import load_config
from app.history import HistoryDB
from app.monitor import Monitor, due_daily
from datetime import datetime
from zoneinfo import ZoneInfo

SAMPLE = """@stat
cpu  100 0 100 800 0 0 0 0 0 0
@mem
MemTotal: 1000 kB
MemAvailable: 500 kB
@temp
coretemp 50000
@df
Filesystem 1-blocks Used Available Capacity Mounted on
/dev/sda1 100 95 5 95% /
"""


class SSH:
    async def run(self, cmd, timeout=15):
        return SAMPLE


class Docker:
    def __init__(self):
        self.state = "running"

    async def containers(self):
        return [{"Names": ["/web"], "State": self.state}]


class Push:
    def __init__(self):
        self.sent = []

    async def send(self, title, body, url="/"):
        self.sent.append((title, body, url))


class Hook:
    def __init__(self):
        self.calls = []

    async def tick(self, n, now):
        self.calls.append(n)
        return [("algo pasa", "/#status")] if n == 1 else []


def make(tmp_path, yml=""):
    p = tmp_path / "c.yml"
    p.write_text(yml or "name: casa\ndisk_alert_percent: 90\n")
    cfg = load_config(str(p), {})
    push, docker, hook = Push(), Docker(), Hook()
    m = Monitor(cfg, SSH(), docker, HistoryDB(str(tmp_path / "h.db")), push, hooks=[hook])
    return m, push, docker, hook


async def test_tick_records_history_and_runs_hooks(tmp_path):
    m, push, docker, hook = make(tmp_path)
    await m.tick(0)
    assert m.history.query(since=0, bucket=60)[0]["temp"] == 50.0
    assert hook.calls == [0]
    docker.state = "exited"
    await m.tick(1)
    titles = {t for t, _, _ in push.sent}
    bodies = [b for _, b, _ in push.sent]
    assert titles == {"casa"}
    assert "web se ha parado (exited)" in bodies and "algo pasa" in bodies


async def test_hook_error_does_not_stop_others(tmp_path):
    m, push, docker, hook = make(tmp_path)

    class Bad:
        async def tick(self, n, now):
            raise RuntimeError("boom")

    m.hooks.insert(0, Bad())
    await m.tick(1)
    assert hook.calls == [1]


def test_due_daily():
    tz = ZoneInfo("Europe/Madrid")
    at = datetime(2026, 10, 15, 4, 30, tzinfo=tz)
    assert due_daily(at, "04:00", None)
    assert not due_daily(at, "04:00", "2026-10-15")
    assert due_daily(at, "04:00", "2026-10-14")
    assert not due_daily(at, "05:30", "2026-10-14")
    assert not due_daily(at, None, None)
