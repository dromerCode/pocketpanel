import json
import os
import stat

from fastapi.testclient import TestClient

from app import auth
from app.authstore import load_auth, save_pin
from app.config import load_config
from app.config_writer import apply_changes
from app.main import create_app, limiter

CODE = "K7P-4QM"


def make(tmp_path, env_extra=None, yml="name: x\n"):
    p = tmp_path / "config.yml"
    p.write_text(yml)
    env = {"PANEL_DATA": str(tmp_path / "data"), "PANEL_UPLOADS": str(tmp_path / "up"), "PANEL_CONFIG": str(p),
           "PANEL_SETUP_CODE": CODE, **(env_extra or {})}
    restarts = []
    limiter.fails.clear()
    c = TestClient(create_app(load_config(str(p), env), restart=lambda: restarts.append(1)))
    return c, p, restarts


def test_auth_json_wins_over_env_and_is_private(tmp_path):
    d = tmp_path / "data"
    save_pin(str(d), "4821")
    assert stat.S_IMODE(os.stat(d / "auth.json").st_mode) == 0o600
    c = load_config(str(tmp_path / "none.yml"), {"PANEL_DATA": str(d), "PANEL_PIN_HASH": auth.hash_pin("1111")})
    assert auth.verify_pin("4821", c.pin_hash) and not auth.verify_pin("1111", c.pin_hash)


def test_secret_generated_and_kept_when_missing(tmp_path):
    c1, _, _ = make(tmp_path)
    s1 = load_auth(str(tmp_path / "data"))["secret"]
    assert len(s1) > 30
    c2, _, _ = make(tmp_path)
    assert load_auth(str(tmp_path / "data"))["secret"] == s1


def test_setup_needed_and_code_check(tmp_path):
    c, _, _ = make(tmp_path)
    assert c.get("/api/setup").json() == {"needed": True}
    assert c.get("/api/setup", params={"code": "MAL-000"}).status_code == 403
    r = c.get("/api/setup", params={"code": CODE}).json()
    assert r["needed"] is True and r["timezone"] and [m["name"] for m in r["modules"]][:3] == ["terminal", "actions", "updates"]
    assert c.get("/api/me").status_code == 401


def test_setup_code_attempts_limited(tmp_path):
    c, _, _ = make(tmp_path)
    for _ in range(5):
        c.get("/api/setup", params={"code": "MAL-000"})
    assert c.get("/api/setup", params={"code": CODE}).status_code == 429


def test_setup_completes_once(tmp_path):
    c, p, restarts = make(tmp_path)
    body = {"code": CODE, "name": "casa", "timezone": "Europe/Madrid", "pin": "4821",
            "modules": {"terminal": {"enabled": False},
                        "raid": {"enabled": True, "values": {"device": "/dev/md1"}},
                        "jellyfin": {"enabled": True, "values": {"jfa_pass": "pw"}}}}
    r = c.post("/api/setup", json=body)
    assert r.status_code == 200 and restarts == [1]
    cfg = load_config(str(p), {"PANEL_DATA": str(tmp_path / "data")})
    assert cfg.name == "casa" and not cfg.enabled("terminal") and cfg.mod("raid")["device"] == "/dev/md1"
    assert auth.verify_pin("4821", cfg.pin_hash) and cfg.jfa_pass == "pw"
    assert "pw" not in p.read_text()
    assert c.get("/api/me").status_code == 200  # ya con sesión
    # y el código ya no sirve
    c2, _, _ = make(tmp_path)
    assert c2.get("/api/setup").json() == {"needed": False}
    assert c2.post("/api/setup", json=body).status_code == 409


def test_setup_validates_everything_before_writing(tmp_path):
    c, p, restarts = make(tmp_path)
    before = p.read_text()
    bad = {"code": CODE, "name": "casa", "timezone": "Europe/Madrid", "pin": "4821",
           "modules": {"backups": {"enabled": True, "values": {"source": "/srv"}}}}
    r = c.post("/api/setup", json=bad)
    assert r.status_code == 400 and "modules.backups.dest" in r.json()["detail"]
    assert p.read_text() == before and restarts == [] and "pin_hash" not in load_auth(str(tmp_path / "data"))
    for pin in ("12", "abcd", "1234567890123"):
        assert c.post("/api/setup", json={**bad, "modules": {}, "pin": pin}).status_code == 400


def test_setup_routes_need_code(tmp_path):
    c, _, _ = make(tmp_path)
    assert c.post("/api/setup", json={"code": "MAL-000"}).status_code == 403
    assert c.post("/api/setup/check/raid", json={"code": "MAL-000", "values": {}}).status_code == 403


def test_installs_with_env_pin_never_see_setup(tmp_path):
    c, _, _ = make(tmp_path, {"PANEL_PIN_HASH": auth.hash_pin("1234")})
    assert c.get("/api/setup").json() == {"needed": False}
    assert c.get("/api/setup", params={"code": CODE}).json() == {"needed": False}


def test_apply_changes_many_modules_at_once(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text("# hola\nname: x\n")
    apply_changes(str(p), {}, general={"name": "y"}, modules={"raid": {"enabled": True}, "terminal": {"enabled": False}})
    c = load_config(str(p), {})
    assert c.name == "y" and c.enabled("raid") and not c.enabled("terminal") and "# hola" in p.read_text()
