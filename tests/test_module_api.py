import json

from fastapi.testclient import TestClient

from app import auth
from app.config import load_config
from app.main import create_app

YML = "name: casa  # comentario\nmodules:\n  raid: {enabled: false, device: /dev/md5}\n"


def make(tmp_path, yml=YML):
    p = tmp_path / "config.yml"
    p.write_text(yml)
    env = {"PANEL_PIN_HASH": auth.hash_pin("1234"), "PANEL_SECRET": "s", "PANEL_DATA": str(tmp_path / "data"),
           "PANEL_UPLOADS": str(tmp_path / "up"), "PANEL_CONFIG": str(p)}
    restarts = []
    c = TestClient(create_app(load_config(str(p), env), restart=lambda: restarts.append(1)))
    assert c.post("/api/login", json={"pin": "1234"}).status_code == 200
    return c, p, restarts


def test_list_modules(tmp_path):
    c, _, _ = make(tmp_path)
    r = c.get("/api/modules").json()
    assert r["general"]["values"]["name"] == "casa"
    mods = {m["name"]: m for m in r["modules"]}
    assert mods["terminal"]["enabled"] is True and mods["raid"]["enabled"] is False
    assert mods["raid"]["values"]["device"] == "/dev/md5"  # aunque esté apagado, lo guardado se ve
    assert mods["raid"]["title"] == "RAID" and mods["raid"]["fields"]
    assert mods["jellyfin"]["values"]["jfa_pass"] == {"set": False}


def test_enable_module_writes_and_restarts(tmp_path):
    c, p, restarts = make(tmp_path)
    r = c.put("/api/modules/raid", json={"enabled": True, "values": {"device": "/dev/md1"}})
    assert r.status_code == 200 and r.json() == {"restart": True}
    assert restarts == [1] and "# comentario" in p.read_text()
    assert load_config(str(p), {}).mod("raid")["device"] == "/dev/md1"


def test_invalid_is_400_and_nothing_changes(tmp_path):
    c, p, restarts = make(tmp_path)
    r = c.put("/api/modules/backups", json={"enabled": True, "values": {"source": "/srv"}})
    assert r.status_code == 400 and "modules.backups.dest" in r.json()["detail"]
    assert p.read_text() == YML and restarts == []


def test_unknown_module_404(tmp_path):
    c, _, _ = make(tmp_path)
    assert c.put("/api/modules/nope", json={"enabled": True}).status_code == 404


def test_secrets_go_to_secrets_file(tmp_path):
    c, p, _ = make(tmp_path)
    r = c.put("/api/modules/jellyfin", json={"enabled": True, "values": {"jfa_user": "admin", "jfa_pass": "pw",
                                                                         "public_url": "https://j.example.com"}})
    assert r.status_code == 200
    assert "pw" not in p.read_text() and "admin" not in p.read_text()
    assert json.loads((tmp_path / "data" / "secrets.json").read_text())["jellyfin"]["jfa_pass"] == "pw"
    mods = {m["name"]: m for m in c.get("/api/modules").json()["modules"]}
    assert mods["jellyfin"]["values"]["jfa_pass"] == {"set": True}


def test_general_settings(tmp_path):
    c, p, restarts = make(tmp_path)
    assert c.put("/api/settings", json={"values": {"name": "homelab", "disk_alert_percent": 80}}).status_code == 200
    assert load_config(str(p), {}).name == "homelab" and restarts == [1]
    assert c.put("/api/settings", json={"values": {"disk_alert_percent": "mucho"}}).status_code == 400


def test_busy_refuses(tmp_path):
    c, p, restarts = make(tmp_path)
    c.app.state.ctx.busy = lambda: "hay un backup en marcha"
    r = c.put("/api/modules/raid", json={"enabled": True})
    assert r.status_code == 409 and "backup" in r.json()["detail"] and restarts == []


def test_requires_auth(tmp_path):
    c, _, _ = make(tmp_path)
    c.post("/api/logout")
    c.cookies.clear()
    assert c.get("/api/modules").status_code == 401
    assert c.put("/api/settings", json={"values": {}}).status_code == 401


def test_check_uses_proposed_values(tmp_path):
    c, _, _ = make(tmp_path)

    class SSH:
        cmds = []

        async def run(self, cmd, timeout=15):
            self.cmds.append(cmd)
            return "PPCHK|device|1|error|\nPPCHK|mdadm|1|warn|\nPPCHK|smartctl|0|warn|\n"

    ssh = SSH()
    c.app.state.ctx.ssh = ssh
    r = c.post("/api/modules/raid/check", json={"values": {"device": "/dev/md9"}})
    assert r.status_code == 200
    assert [x["ok"] for x in r.json()] == [True, True, False]
    assert "/dev/md9" in ssh.cmds[0]
    assert c.post("/api/modules/nope/check", json={"values": {}}).status_code == 404


def test_sites_api(tmp_path):
    c, _, _ = make(tmp_path, "modules:\n  sites: {enabled: true, urls: ['https://a.example.com']}\n")
    r = c.get("/api/sites").json()
    assert r[0]["name"] == "a.example.com" and r[0]["ok"] is None


def test_downloads_api_reports_each_service(tmp_path):
    c, _, _ = make(tmp_path, "modules:\n  downloads: {enabled: true, qbittorrent_url: 'http://127.0.0.1:1',"
                             " sonarr_url: 'http://127.0.0.1:1'}\n")
    r = c.get("/api/downloads").json()
    assert r["qbit"]["ok"] is False and "no responde" in r["qbit"]["error"]
    assert [a["kind"] for a in r["arr"]] == ["sonarr"] and r["arr"][0]["ok"] is False
    assert c.post(f"/api/downloads/torrents/{'z' * 40}/pause").status_code == 400
    assert c.post(f"/api/downloads/torrents/{'a' * 40}/explode").status_code == 404


def test_downloads_secrets_are_masked(tmp_path):
    c, _, _ = make(tmp_path)
    assert c.put("/api/modules/downloads", json={"enabled": True, "values": {
        "qbittorrent_url": "http://qb", "qbittorrent_pass": "pw", "sonarr_key": "k"}}).status_code == 200
    mods = {m["name"]: m for m in c.get("/api/modules").json()["modules"]}
    v = mods["downloads"]["values"]
    assert v["qbittorrent_pass"] == {"set": True} and v["sonarr_key"] == {"set": True} and v["radarr_key"] == {"set": False}


def test_downloads_summary(tmp_path):
    c, _, _ = make(tmp_path, "modules:\n  downloads: {enabled: true, qbittorrent_url: 'http://qb'}\n")

    class Q:
        async def torrents(self):
            return [{"hash": "a" * 40, "name": "x", "done": False, "paused": False, "dl": 10},
                    {"hash": "b" * 40, "name": "y", "done": False, "paused": True, "dl": 0},
                    {"hash": "c" * 40, "name": "z", "done": True, "paused": False, "dl": 0}]

        async def transfer(self):
            return {"dl": 10, "up": 5}

    c.app.state.ctx.downloads_qbit = Q()
    assert c.get("/api/downloads/summary").json() == {"active": 1, "paused": 1, "dl": 10, "up": 5, "error": None}
