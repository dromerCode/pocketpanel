import os
import subprocess
from pathlib import Path

import pytest

from app.backup import backup_env, parse_result, run_command, script, snapshot_name

OPTS = {"source": "/srv/appdata", "dest": "bk@nas:/backups/pp", "ssh_key": "/home/r/.ssh/id_bk",
        "ssh_options": "-p 2222", "keep_days": 5, "excludes": ["cache/", "*.log"], "at": "04:00"}
BIN = Path(__file__).parent / "bin"


def test_snapshot_name():
    assert snapshot_name("2026-10-13") == "2026-10-13"
    assert snapshot_name("2026-10-13", "antes-jellyfin") == "2026-10-13-antes-jellyfin"
    with pytest.raises(ValueError):
        snapshot_name("2026-10-13", "x; rm -rf /")


def test_env_from_config():
    assert backup_env(OPTS) == {"SRC": "/srv/appdata/", "DEST_HOST": "bk@nas", "DEST_PATH": "/backups/pp",
                                "SSH_OPTS": "-p 2222 -o BatchMode=yes -o ConnectTimeout=10 -i /home/r/.ssh/id_bk",
                                "KEEP_DAYS": "5", "EXCLUDES": "cache/\n*.log"}


@pytest.mark.parametrize("dest", ["nas", "nas:relative/path", ":/x"])
def test_dest_needs_host_and_absolute_path(dest):
    with pytest.raises(ValueError):
        backup_env({**OPTS, "dest": dest})


def test_run_command_root_or_user_mode():
    c = run_command("2026-10-14", OPTS)
    assert "sudo -n /etc/pocketpanel/backup.sh 2026-10-14" in c
    assert "sudo -n -l /etc/pocketpanel/backup.sh" in c and "sudoers.d" not in c
    assert "SRC=/srv/appdata/" in c and "--link-dest=../latest" in c
    assert "bash -c " in c and " backup.sh 2026-10-14 2>&1 </dev/null" in c


def test_parse_result():
    assert parse_result("bla\nPP_OK 100 40 3\n") == {
        "ok": True, "total": 100, "size": 40, "count": 3, "denied": 0, "denied_dirs": [], "root": False,
        "changed": []}
    r = parse_result("PP_MODE root\nPP_DENIED 12\nPP_DIR    8 homeassistant/config\nPP_OK 1 2 3\n")
    assert r["denied"] == 12 and r["denied_dirs"] == ["homeassistant/config"] and r["root"] is True
    assert parse_result("rsync: error\nPP_FAIL rsync salió con 12\n") == {"ok": False, "error": "rsync salió con 12"}
    assert parse_result("")["ok"] is False


@pytest.mark.parametrize("name", ["backup.sh", "restore.sh"])
def test_scripts_are_valid_bash(name):
    subprocess.run(["bash", "-n", "-c", script(name)], check=True)


def _run(cmd: str) -> str:
    env = {**os.environ, "PATH": f"{BIN}:{os.environ['PATH']}"}
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, env=env, timeout=60).stdout


@pytest.mark.skipif(not __import__("shutil").which("rsync"), reason="sin rsync")
def test_backup_and_restore_for_real(tmp_path):
    from app.restore import parse_preview, restore_command
    src, dest = tmp_path / "appdata", tmp_path / "dest"
    (src / "app1" / "cache").mkdir(parents=True)
    (src / "app1" / "db.sqlite").write_text("v1")
    (src / "app1" / "cache" / "big").write_text("x")
    (src / "app1" / "x.log").write_text("log")
    opts = {**OPTS, "source": str(src), "dest": f"me@local:{dest}", "ssh_key": "", "ssh_options": ""}

    out = _run(run_command("2026-10-14", opts))
    r = parse_result(out)
    assert r["ok"] and r["count"] == 1 and not r["root"], out
    snap = dest / "2026-10-14"
    assert (snap / "app1" / "db.sqlite").read_text() == "v1"
    assert not (snap / "app1" / "cache").exists() and not (snap / "app1" / "x.log").exists()
    assert (snap / ".pocketpanel-complete").exists() and (dest / "latest").resolve() == snap

    (src / "app1" / "db.sqlite").write_text("v2-roto")
    p = parse_preview(_run(restore_command("2026-10-14", "app1", "dry", opts)))
    assert p["changes"] == 1
    assert "PP_RESTORED" in _run(restore_command("2026-10-14", "app1", "run", opts))
    assert (src / "app1" / "db.sqlite").read_text() == "v1"
    assert (src / "app1" / "cache" / "big").exists()  # lo excluido no se borra al restaurar


@pytest.mark.skipif(not __import__("shutil").which("rsync"), reason="sin rsync")
def test_retention_keeps_keep_days(tmp_path):
    src, dest = tmp_path / "appdata", tmp_path / "dest"
    (src / "a").mkdir(parents=True)
    for d in ["2026-10-01", "2026-10-02", "2026-10-03"]:
        (dest / d).mkdir(parents=True)
    opts = {**OPTS, "source": str(src), "dest": f"me@local:{dest}", "ssh_key": "", "ssh_options": "", "keep_days": 2}
    assert parse_result(_run(run_command("2026-10-04", opts)))["ok"]
    assert sorted(p.name for p in dest.iterdir() if p.name.startswith("20")) == ["2026-10-03", "2026-10-04"]
