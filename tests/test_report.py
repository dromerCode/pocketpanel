import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.modules.claude.report import Report


class SSH:
    async def run(self, cmd, timeout=15):
        return "@mem\nMemTotal: 100 kB\nMemAvailable: 50 kB\n@df\nFilesystem\n"


class Docker:
    async def containers(self):
        return [{"Names": ["/sonarr"], "State": "running", "Status": "Up 1 hour"}]

    async def inspect_container(self, name):
        return {"RestartCount": 3, "State": {"StartedAt": "x", "ExitCode": 0}}


class Backup:
    def state(self):
        return {"last": {"ok": True}}


class Updater:
    results = {"jellyfin": {"status": "update"}, "kavita": {"status": "ok"}}
    checked_at = 1


class Claude:
    def __init__(self, running=False):
        self.running, self.turn, self.sent = running, 4, []

    async def send(self, text, session):
        self.turn += 1
        self.sent.append(text)


class Push:
    def __init__(self):
        self.sent = []

    async def send(self, title, body, url):
        self.sent.append((title, body, url))


def make(tmp_path, claude, notes="", backup=True):
    cfg = SimpleNamespace(name="casa", data_dir=str(tmp_path), host_dir="/opt/pocketpanel", disks=[])
    ctx = SimpleNamespace(cfg=cfg, ssh=SSH(), docker=Docker(), backup=Backup() if backup else None,
                          updater=Updater(), raid=None, history=None, push=Push(), tz=ZoneInfo("Europe/Madrid"))
    return Report(ctx, claude, notes=notes)


async def test_run_writes_data_and_asks_claude(tmp_path):
    c = Claude()
    r = make(tmp_path, c)
    assert await r.run() is True
    files = list(tmp_path.glob("informe-*.json"))
    data = json.loads(files[0].read_text())
    assert data["contenedores"][0]["restart_count"] == 3 and data["actualizaciones"] == ["jellyfin"]
    assert "SOLO LECTURA" in c.sent[0] and f"/opt/pocketpanel/data/{files[0].name}" in c.sent[0]
    assert r.is_report_turn(5) and not r.is_report_turn(4)
    assert r.state()["day"] == files[0].name[len("informe-"):-len(".json")]
    assert "el administrador" in c.sent[0]


async def test_busy_claude_postpones(tmp_path):
    r = make(tmp_path, Claude(running=True))
    assert await r.run() is False and r.state() == {}


async def test_finished_always_pushes(tmp_path):
    r = make(tmp_path, Claude())
    await r.finished("sid", "✅ Todo bien")
    assert r.ctx.push.sent == [("Resumen de casa", "✅ Todo bien", "/#claude/sid")]
    assert r.state()["summary"] == "✅ Todo bien"


def test_extract_summary():
    from app.modules.claude.report import extract_summary
    t = "**Detalles**\n- todo en marcha\n\nRESUMEN: ✅ **Todo bien**.\nBackup ok, 14 actualizaciones pendientes."
    assert extract_summary(t) == "✅ Todo bien.\nBackup ok, 14 actualizaciones pendientes."
    assert extract_summary("párrafo uno\n\n⚠️ sin marcador") == "⚠️ sin marcador"
    assert len(extract_summary("RESUMEN: " + "x" * 500)) == 301


async def test_notes_and_missing_modules(tmp_path):
    c = Claude()
    r = make(tmp_path, c, notes="El disco /mnt/viejo al 95% es normal.", backup=False)
    assert await r.run() is True
    assert "El disco /mnt/viejo al 95% es normal." in c.sent[0]
    data = json.loads(next(tmp_path.glob("informe-*.json")).read_text())
    assert data["backup"] is None and data["raid"] is None
