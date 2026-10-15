import asyncio

import pytest

from app.restore import Restorer, app_label, apps_from_mounts, parse_preview

OPTS = {"source": "/srv/appdata", "dest": "bk@nas:/backups", "ssh_key": "", "ssh_options": "", "keep_days": 7,
        "excludes": []}


def test_app_label():
    assert app_label("jellyfin") == "antes-restaurar-jellyfin"
    assert app_label("Big_Bear.JFA-go") == "antes-restaurar-big-bear-jfa-go"
    assert len(app_label("x" * 80)) <= 40


def test_apps_from_mounts():
    mounts = [{"Source": "/srv/appdata/jellyfin/config"}, {"Source": "/srv/appdata/jellyfin/cache"},
              {"Source": "/media/HDD6TB"}, {"Source": "/srv/appdata/big-bear-jfa-go/.config"}]
    assert apps_from_mounts(mounts, "/srv/appdata") == ["jellyfin", "big-bear-jfa-go"]
    assert apps_from_mounts(None, "/srv/appdata") == []
    assert apps_from_mounts([{"Source": "/srv/appdata2/x"}], "/srv/appdata/") == []


def test_parse_preview():
    r = parse_preview("PP_CHANGES 3\nPP_FILE >f..t...... config/a.db\n")
    assert r == {"changes": 3, "files": [">f..t...... config/a.db"]}
    with pytest.raises(RuntimeError, match="no tiene"):
        parse_preview("PP_FAIL la copia X no tiene jellyfin\n")


class FakeBackup:
    def __init__(self, ok=True):
        self.ok, self.labels = ok, []

    async def run(self, label=""):
        self.labels.append(label)
        return {"ok": self.ok, "snapshot": f"2026-10-14-{label}", "error": "boom"}


class FakeDocker:
    def __init__(self):
        self.calls = []

    async def containers(self):
        return [{"Names": ["/jellyfin"], "State": "running", "Mounts": [{"Source": "/srv/appdata/jellyfin/config"}]},
                {"Names": ["/sonarr"], "State": "running", "Mounts": [{"Source": "/srv/appdata/sonarr/config"}]}]

    async def stop(self, n): self.calls.append(("stop", n))
    async def start(self, n): self.calls.append(("start", n))


class FakeSSH:
    def __init__(self, out):
        self.out, self.cmds = out, []

    async def run(self, cmd, timeout=15):
        self.cmds.append(cmd)
        return self.out


async def wait(j):
    while j.status == "running":
        await asyncio.sleep(0)


async def test_restore_stops_only_affected_and_restarts():
    d, b, s = FakeDocker(), FakeBackup(), FakeSSH("PP_RESTORED\n")
    j = Restorer(s, d, b, OPTS).start("2026-10-13", "jellyfin")
    await wait(j)
    assert j.status == "ok", j.lines
    assert b.labels == ["antes-restaurar-jellyfin"]
    assert d.calls == [("stop", "jellyfin"), ("start", "jellyfin")]
    assert len(s.cmds) == 1 and "sudo -n /etc/pocketpanel/restore.sh 2026-10-13 jellyfin run" in s.cmds[0]
    assert "SRC=/srv/appdata/" in s.cmds[0]


async def test_restore_failure_still_restarts():
    d, s = FakeDocker(), FakeSSH("PP_FAIL rsync salió con 12\n")
    j = Restorer(s, d, FakeBackup(), OPTS).start("2026-10-13", "jellyfin")
    await wait(j)
    assert j.status == "failed" and d.calls[-1] == ("start", "jellyfin")


async def test_no_restore_if_safety_backup_fails():
    d, s = FakeDocker(), FakeSSH("PP_RESTORED\n")
    j = Restorer(s, d, FakeBackup(ok=False), OPTS).start("2026-10-13", "jellyfin")
    await wait(j)
    assert j.status == "failed" and s.cmds == [] and d.calls == []


def test_rejects_bad_input():
    r = Restorer(None, None, None, OPTS)
    for snap, app in [("x; rm", "jellyfin"), ("2026-10-13", "../etc"), ("2026-10-13", "a b")]:
        with pytest.raises(ValueError):
            r.start(snap, app)


async def test_snapshots_only_complete():
    s = FakeSSH("2026-10-14\n2026-10-15-antes-x\nbasura\n")
    snaps = await Restorer(s, None, None, OPTS).snapshots()
    assert snaps == ["2026-10-15-antes-x", "2026-10-14"]
    assert ".pocketpanel-complete" in s.cmds[0] and "/backups" in s.cmds[0] and "bk@nas" in s.cmds[0]
