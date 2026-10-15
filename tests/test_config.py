import pytest

from app.config import ConfigError, load_config


def cfg(tmp_path, text: str, env: dict | None = None):
    p = tmp_path / "config.yml"
    p.write_text(text)
    return load_config(str(p), env or {})


def test_missing_file_gives_defaults(tmp_path):
    c = load_config(str(tmp_path / "nope.yml"), {})
    assert c.name == "servidor"
    assert c.timezone == "Europe/Madrid"
    assert [m for m in c.modules] == ["terminal", "actions", "updates"]
    assert c.enabled("terminal") and not c.enabled("raid")


def test_enabling_module_merges_defaults(tmp_path):
    c = cfg(tmp_path, "modules:\n  raid: {enabled: true}\n")
    assert c.enabled("raid")
    assert c.mod("raid")["device"] == "/dev/md0"
    assert c.mod("raid")["ssh"] == ""


def test_disabling_default_module(tmp_path):
    c = cfg(tmp_path, "modules:\n  terminal: {enabled: false}\n")
    assert not c.enabled("terminal")
    assert "terminal" not in c.modules


def test_unknown_module(tmp_path):
    with pytest.raises(ConfigError, match="modules.foo"):
        cfg(tmp_path, "modules:\n  foo: {enabled: true}\n")


def test_enabled_must_be_bool(tmp_path):
    with pytest.raises(ConfigError, match="modules.raid.enabled"):
        cfg(tmp_path, "modules:\n  raid: {enabled: 'yes'}\n")


def test_backups_need_dest(tmp_path):
    with pytest.raises(ConfigError, match="modules.backups.dest"):
        cfg(tmp_path, "modules:\n  backups: {enabled: true, source: /srv/appdata}\n")


def test_bad_time(tmp_path):
    with pytest.raises(ConfigError, match="modules.updates.check_at"):
        cfg(tmp_path, "modules:\n  updates: {enabled: true, check_at: '25:00'}\n")


def test_report_at_can_be_null(tmp_path):
    c = cfg(tmp_path, "modules:\n  claude: {enabled: true, report_at: null}\n")
    assert c.mod("claude")["report_at"] is None


def test_unknown_module_key(tmp_path):
    with pytest.raises(ConfigError, match="modules.raid.devic"):
        cfg(tmp_path, "modules:\n  raid: {enabled: true, devic: /dev/md1}\n")


def test_top_level_types(tmp_path):
    with pytest.raises(ConfigError, match="disks"):
        cfg(tmp_path, "disks: /mnt\n")


def test_invalid_yaml(tmp_path):
    with pytest.raises(ConfigError, match="config.yml"):
        cfg(tmp_path, "name: [\n")


def test_env_values(tmp_path):
    c = cfg(tmp_path, "name: casa\n", {"PANEL_HOST_USER": "ramon", "PANEL_SSH_PORT": "2222",
                                       "PANEL_HOST_DIR": "/opt/pocketpanel", "CLAUDE_HOME": "/home/ramon"})
    assert c.name == "casa"
    assert c.ssh_user == "ramon" and c.ssh_port == 2222
    assert c.host_dir == "/opt/pocketpanel"
    assert c.claude_home == "/home/ramon" and c.claude_cwd == "/home/ramon"


def test_host_env_strings(tmp_path):
    c = cfg(tmp_path, "host_env: {DOCKER_CONFIG: /tmp/d}\n")
    assert c.host_env == {"DOCKER_CONFIG": "/tmp/d"}


def test_example_config_valid_with_every_module_enabled(tmp_path):
    from pathlib import Path

    import yaml
    raw = yaml.safe_load((Path(__file__).parent.parent / "config.example.yml").read_text())
    for m in raw["modules"].values():
        m["enabled"] = True
    p = tmp_path / "c.yml"
    p.write_text(yaml.safe_dump(raw))
    c = load_config(str(p), {})
    assert list(c.modules) == ["terminal", "actions", "updates", "claude", "backups", "raid", "jellyfin"]
