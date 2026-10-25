import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app, limiter


@pytest.fixture
def client():
    limiter.fails.clear()
    return TestClient(app)


def login(c):
    r = c.post("/api/login", json={"pin": "1234"})
    assert r.status_code == 200
    return c


def test_me_requires_cookie(client):
    assert client.get("/api/me").status_code == 401


def test_login_sets_cookie(client):
    login(client)
    assert client.get("/api/me").status_code == 200


def test_bad_pin(client):
    assert client.post("/api/login", json={"pin": "0000"}).status_code == 401


def test_login_rate_limited(client):
    for _ in range(5):
        client.post("/api/login", json={"pin": "0000"})
    assert client.post("/api/login", json={"pin": "1234"}).status_code == 429


def test_spoofed_forwarded_for_does_not_reset_limiter(client):
    # Cambiar X-Forwarded-For en cada intento no puede dar intentos nuevos: con el panel en la LAN o en el
    # tailnet, eso permitía probar todos los PIN. La IP real la pone uvicorn solo si viene de un proxy de confianza.
    for i in range(5):
        client.post("/api/login", json={"pin": "0000"}, headers={"X-Forwarded-For": f"10.0.0.{i}"})
    r = client.post("/api/login", json={"pin": "1234"}, headers={"X-Forwarded-For": "10.0.0.99"})
    assert r.status_code == 429


def test_forwarded_proto_alone_does_not_mark_cookie_secure(client):
    r = client.post("/api/login", json={"pin": "1234"}, headers={"X-Forwarded-Proto": "https"})
    assert "secure" not in r.headers["set-cookie"].lower()


def test_logout(client):
    login(client)
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize("path", ["/ws/term?mode=shell", "/ws/claude", "/ws/logs/jellyfin", "/ws/action/df"])
def test_ws_rejects_without_cookie(client, path):
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(path) as ws:
            ws.receive_text()
    assert e.value.code == 4401


def test_api_requires_auth(client):
    for p in ["/api/system", "/api/containers", "/api/claude/sessions", "/api/raid", "/api/history", "/api/actions",
              "/api/push/key", "/api/backup", "/api/updates", "/api/updates/x/job", "/api/jfa/users", "/api/jfa/invites"]:
        assert client.get(p).status_code == 401


def test_upload_requires_auth(client):
    assert client.post("/api/claude/upload", files={"file": ("a.txt", b"x")}).status_code == 401


def test_upload_saves_file(client, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "uploads_dir", str(tmp_path))
    login(client)
    r = client.post("/api/claude/upload", files={"file": ("../mi foto.png", b"PNG")})
    assert r.status_code == 200
    body = r.json()
    assert body["path"].startswith(settings.host_dir + "/uploads/") and body["path"].endswith("-mi_foto.png")
    saved = list(tmp_path.iterdir())
    assert len(saved) == 1 and saved[0].read_bytes() == b"PNG"
