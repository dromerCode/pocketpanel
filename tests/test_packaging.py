from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_dockerfile_sets_local_username():
    # asyncssh necesita un usuario local (USER/LOGNAME) y el contenedor corre con un UID sin entrada en /etc/passwd
    env = [l for l in (ROOT / "Dockerfile").read_text().splitlines() if l.startswith("ENV ")]
    assert any(" USER=" in l for l in env)
