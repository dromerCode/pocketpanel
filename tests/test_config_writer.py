import os
import stat

import pytest

from app.config import ConfigError, load_config
from app.config_writer import apply_changes
from app.secrets import load_secrets, save_secrets

YML = """# mi servidor
name: casa   # el nombre bonito
modules:
  raid:
    enabled: false   # sin RAID de momento
"""


def env(tmp_path):
    return {"PANEL_DATA": str(tmp_path / "data")}


def test_enable_module_keeps_comments_and_other_keys(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(YML)
    apply_changes(str(p), env(tmp_path), module="raid", enabled=True, values={"device": "/dev/md1"})
    text = p.read_text()
    assert "# mi servidor" in text and "# el nombre bonito" in text and "# sin RAID de momento" in text
    c = load_config(str(p), env(tmp_path))
    assert c.name == "casa" and c.enabled("raid") and c.mod("raid")["device"] == "/dev/md1"


def test_invalid_change_leaves_file_untouched(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(YML)
    with pytest.raises(ConfigError, match="modules.backups.dest"):
        apply_changes(str(p), env(tmp_path), module="backups", enabled=True, values={"source": "/srv"})
    assert p.read_text() == YML


def test_unknown_key_rejected(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(YML)
    with pytest.raises(ConfigError, match="modules.raid.devic"):
        apply_changes(str(p), env(tmp_path), module="raid", values={"devic": "x"})
    with pytest.raises(ConfigError, match="modules.nope"):
        apply_changes(str(p), env(tmp_path), module="nope", enabled=True)


def test_general_settings(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(YML)
    apply_changes(str(p), env(tmp_path), general={"name": "homelab", "disks": ["/", "/mnt/*"]})
    c = load_config(str(p), env(tmp_path))
    assert c.name == "homelab" and c.disks == ["/", "/mnt/*"]
    with pytest.raises(ConfigError, match="modules"):
        apply_changes(str(p), env(tmp_path), general={"modules": {}})


def test_creates_missing_file(tmp_path):
    p = tmp_path / "config.yml"
    apply_changes(str(p), env(tmp_path), module="terminal", enabled=False)
    assert not load_config(str(p), env(tmp_path)).enabled("terminal")


def test_writes_in_place(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(YML)
    ino = os.stat(p).st_ino
    apply_changes(str(p), env(tmp_path), general={"name": "x"})
    assert os.stat(p).st_ino == ino  # es un bind mount: nada de renombrar


def test_report_at_null_from_ui(tmp_path):
    p = tmp_path / "config.yml"
    apply_changes(str(p), env(tmp_path), module="claude", enabled=True, values={"report_at": None})
    assert load_config(str(p), env(tmp_path)).mod("claude")["report_at"] is None


def test_secrets_saved_private_and_loaded(tmp_path):
    d = tmp_path / "data"
    save_secrets(str(d), "jellyfin", {"jfa_user": "admin", "jfa_pass": "s3cret"})
    f = d / "secrets.json"
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    save_secrets(str(d), "jellyfin", {"jfa_pass": ""})  # vacío = no cambiar
    assert load_secrets(str(d)) == {"jellyfin": {"jfa_user": "admin", "jfa_pass": "s3cret"}}
    c = load_config(str(tmp_path / "none.yml"), {"PANEL_DATA": str(d), "PANEL_JFA_USER": "env-user"})
    assert c.jfa_user == "admin" and c.jfa_pass == "s3cret"


def test_env_secret_is_fallback(tmp_path):
    c = load_config(str(tmp_path / "none.yml"), {"PANEL_DATA": str(tmp_path), "PANEL_JFA_USER": "env-user"})
    assert c.jfa_user == "env-user"
