from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_dockerfile_sets_local_username():
    # asyncssh necesita un usuario local (USER/LOGNAME) y el contenedor corre con un UID sin entrada en /etc/passwd
    env = [l for l in (ROOT / "Dockerfile").read_text().splitlines() if l.startswith("ENV ")]
    assert any(" USER=" in l for l in env)


def test_dockerfile_bind_is_configurable():
    # Por defecto solo 127.0.0.1 (tailscale serve); PANEL_BIND=0.0.0.0 lo abre en el puerto sin depender de Tailscale
    df = (ROOT / "Dockerfile").read_text()
    assert "PANEL_BIND=127.0.0.1" in df and "PANEL_TRUSTED_PROXIES=127.0.0.1" in df
    assert '--host \\"$PANEL_BIND\\"' in df and '--forwarded-allow-ips \\"$PANEL_TRUSTED_PROXIES\\"' in df
