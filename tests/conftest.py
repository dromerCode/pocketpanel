import os
import sys
import tempfile
import types
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="pocketpanel-test-")
os.environ.setdefault("PANEL_SECRET", "test-secret")
os.environ["PANEL_CONFIG"] = str(Path(__file__).parent / "fixtures" / "config_all.yml")
os.environ["PANEL_DATA"] = f"{_tmp}/data"
os.environ["PANEL_UPLOADS"] = f"{_tmp}/uploads"
os.environ["PANEL_HOST_DIR"] = "/opt/pocketpanel"

# curl_cffi es dependencia del módulo stocks (se descarga aparte, ver app/deps.py), no del núcleo: si no está en el
# venv, un sustituto basta para montar el módulo (los tests de stocks le pasan su propia sesión falsa)
try:
    import curl_cffi  # noqa: F401
except ImportError:
    _stub = types.ModuleType("curl_cffi.requests")
    _stub.AsyncSession = lambda **kw: None
    sys.modules["curl_cffi"] = types.ModuleType("curl_cffi")
    sys.modules["curl_cffi.requests"] = _stub

import pytest  # noqa: E402

from app import auth  # noqa: E402
from app.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    monkeypatch.setattr(settings, "pin_hash", auth.hash_pin("1234"))
