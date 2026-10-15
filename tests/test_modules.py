import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import auth
from app.config import load_config
from app.main import create_app
from app.modules import MODULES

ALL = """
modules:
  claude: {enabled: true}
  backups: {enabled: true, source: /srv/appdata, dest: "bk@nas:/backups"}
  raid: {enabled: true}
  sites: {enabled: true}
  jellyfin: {enabled: true}
"""
NONE = """
name: casa-ramon
modules:
  terminal: {enabled: false}
  actions: {enabled: false}
  updates: {enabled: false}
"""


def client(tmp_path, yml):
    p = tmp_path / "config.yml"
    p.write_text(yml)
    cfg = load_config(str(p), {"PANEL_PIN_HASH": auth.hash_pin("1234"), "PANEL_SECRET": "s",
                               "PANEL_DATA": str(tmp_path / "data"), "PANEL_UPLOADS": str(tmp_path / "up"),
                               "PANEL_HOST_DIR": "/opt/pocketpanel"})
    c = TestClient(create_app(cfg))
    assert c.post("/api/login", json={"pin": "1234"}).status_code == 200
    return c


def test_me_lists_enabled_modules(tmp_path):
    me = client(tmp_path, ALL).get("/api/me").json()
    assert me["modules"] == MODULES
    assert me["backups"]["source"] == "/srv/appdata"
    assert me["claude"]["diagnosis"]


def test_core_only(tmp_path):
    c = client(tmp_path, NONE)
    me = c.get("/api/me").json()
    assert me == {"name": "casa-ramon", "modules": []}


@pytest.mark.parametrize("path", ["/api/raid", "/api/actions", "/api/backup", "/api/updates", "/api/report",
                                  "/api/jfa/users", "/api/claude/sessions", "/api/restore/snapshots"])
def test_disabled_routes_404(tmp_path, path):
    assert client(tmp_path, NONE).get(path).status_code == 404


@pytest.mark.parametrize("path", ["/ws/term?mode=shell", "/ws/claude", "/ws/action/x"])
def test_disabled_ws_closed(tmp_path, path):
    c = client(tmp_path, NONE)
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(path) as ws:
            ws.receive_text()


def test_core_routes_without_modules(tmp_path):
    c = client(tmp_path, NONE)
    assert c.get("/api/push/key").status_code == 200
    assert c.get("/api/history").status_code == 200


def test_containers_hide_update_flags_without_updates(tmp_path, monkeypatch):
    c = client(tmp_path, NONE)
    ctx = c.app.state.ctx

    async def containers():
        return [{"Id": "a", "Names": ["/web"], "State": "running", "Status": "Up", "Image": "nginx", "Ports": []}]

    async def stats(ids):
        return {}

    monkeypatch.setattr(ctx.docker, "containers", containers)
    monkeypatch.setattr(ctx.docker, "stats", stats)
    svc = c.get("/api/containers").json()[0]
    assert svc["name"] == "web" and svc["update"] is False
