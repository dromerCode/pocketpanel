import httpx
import pytest

from app.modules.sites.sites import SiteMonitor, check_site, label


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_check_site_ok_and_error():
    h = client(lambda r: httpx.Response(200) if r.url.host == "a.example.com" else httpx.Response(502))
    ok = await check_site(h, "https://a.example.com")
    assert ok["ok"] is True and ok["status"] == 200 and ok["ms"] >= 0 and ok["error"] is None
    bad = await check_site(h, "https://b.example.com")
    assert bad["ok"] is False and bad["status"] == 502 and bad["error"] == "HTTP 502"


async def test_check_site_unreachable():
    def boom(r):
        raise httpx.ConnectError("connection refused")
    r = await check_site(client(boom), "https://c.example.com")
    assert r["ok"] is False and r["status"] is None and "connection refused" in r["error"]


def test_label():
    assert label("https://media.example.com/web/") == "media.example.com/web"
    assert label("http://127.0.0.1:8096") == "127.0.0.1:8096"


class Clock:
    def __init__(self):
        self.day = "2026-10-15"


def monitor(states, certs, clock=None):
    """states: url -> lista de códigos que irá devolviendo (None = sin conexión)."""
    def handler(r):
        url = str(r.url).rstrip("/")
        code = states[url].pop(0) if len(states[url]) > 1 else states[url][0]
        if code is None:
            raise httpx.ConnectError("refused")
        return httpx.Response(code)

    async def cert(url):
        return certs.get(url)

    clock = clock or Clock()
    return SiteMonitor({"urls": list(states), "interval": 5, "cert_warn_days": 14}, http=client(handler),
                       cert_days=cert, today=lambda: clock.day), clock


async def test_down_needs_two_failures_and_recovery_is_announced():
    u = "https://a.example.com"
    m, _ = monitor({u: [200, 502, 502, 502, 200]}, {})
    assert await m.check_all() == []
    assert await m.check_all() == []                       # un fallo suelto no avisa
    assert await m.check_all() == [("a.example.com no responde (HTTP 502)", "/#status")]
    assert await m.check_all() == []                       # no se repite
    assert await m.check_all() == [("a.example.com vuelve a funcionar", "/#status")]


async def test_cert_warning_once_a_day():
    u = "https://a.example.com"
    m, clock = monitor({u: [200]}, {u: 9})
    assert await m.check_all() == [("El certificado de a.example.com caduca en 9 días", "/#status")]
    assert await m.check_all() == []
    clock.day = "2026-10-16"
    assert len(await m.check_all()) == 1


async def test_results_view():
    u = "https://a.example.com"
    m, _ = monitor({u: [200]}, {u: 60})
    await m.check_all()
    v = m.view()
    assert v[0]["name"] == "a.example.com" and v[0]["ok"] and v[0]["cert_days"] == 60 and v[0]["checked"]


async def test_tick_respects_interval():
    m, _ = monitor({"https://a.example.com": [200]}, {})
    calls = []

    async def fake():
        calls.append(1)
        return [("x", "/#status")]

    m.check_all = fake  # type: ignore[method-assign]
    got = [await m.tick(n, 0) for n in range(21)]
    assert len(calls) == 3                     # vueltas 0, 10 y 20: cada 5 min con vueltas de 30 s
    assert got[10] == [("x", "/#status")] and got[5] == []


def _tls_server(tmp_path, days):
    import datetime as dt
    import socket
    import ssl
    import threading

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=days, hours=1)).sign(key, hashes.SHA256()))
    (tmp_path / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "k.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                       serialization.NoEncryption()))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "c.pem", tmp_path / "k.pem")
    srv = socket.create_server(("127.0.0.1", 0))

    def serve():
        conn, _ = srv.accept()
        try:
            ctx.wrap_socket(conn, server_side=True).close()
        except OSError:
            pass
    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1]


async def test_cert_days_real_tls(tmp_path):
    from app.modules.sites.sites import cert_days
    port = _tls_server(tmp_path, 30)
    assert await cert_days(f"https://127.0.0.1:{port}/") == 30


async def test_cert_days_http_is_none():
    from app.modules.sites.sites import cert_days
    assert await cert_days("http://127.0.0.1:1/") is None
