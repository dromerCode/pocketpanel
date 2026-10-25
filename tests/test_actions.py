import os
import time

from app.modules.actions.actions import action_command, load_actions
from app.modules.claude.uploads import clean_old, safe_name


def test_load_actions_validates(tmp_path):
    f = tmp_path / "a.yml"
    f.write_text("""
- {id: prune, name: Limpiar Docker, cmd: docker image prune -f, confirm: true}
- {id: prune, name: Duplicada, cmd: echo x}
- {id: "Mal ID", name: x, cmd: echo}
- {id: sin-cmd, name: x}
- {id: df, name: Discos, cmd: df -h}
""")
    acts = load_actions(str(f))
    assert [a["id"] for a in acts] == ["prune", "df"]
    assert acts[0]["confirm"] is True and acts[1]["confirm"] is False


def test_load_actions_missing_or_broken(tmp_path):
    assert load_actions(str(tmp_path / "nope.yml")) == []
    f = tmp_path / "b.yml"
    f.write_text("{{{ no es yaml")
    assert load_actions(str(f)) == []


def test_action_command_merges_stderr():
    c = action_command("df -h", {})
    assert c.endswith("( df -h\n) 2>&1")


def test_safe_name():
    n = safe_name("../../etc/pass wd.png")
    assert "/" not in n and n.endswith("-pass_wd.png")
    assert safe_name("").endswith("-archivo")


def test_clean_old(tmp_path):
    old, new = tmp_path / "old.txt", tmp_path / "new.txt"
    old.write_text("x")
    new.write_text("y")
    t = time.time()
    os.utime(old, (t - 8 * 86400, t - 8 * 86400))
    assert clean_old(str(tmp_path), now=t) == 1
    assert not old.exists() and new.exists()


def test_action_command_exports_host_env():
    c = action_command("docker ps", {"DOCKER_CONFIG": "/tmp/d x"})
    assert "export LANG=C.UTF-8" in c
    assert "DOCKER_CONFIG='/tmp/d x'" in c
