import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="pocketpanel-test-")
os.environ.setdefault("PANEL_SECRET", "test-secret")
os.environ["PANEL_CONFIG"] = str(Path(__file__).parent / "fixtures" / "config_all.yml")
os.environ["PANEL_DATA"] = f"{_tmp}/data"
os.environ["PANEL_UPLOADS"] = f"{_tmp}/uploads"
os.environ["PANEL_HOST_DIR"] = "/opt/pocketpanel"

import pytest  # noqa: E402

from app import auth  # noqa: E402
from app.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    monkeypatch.setattr(settings, "pin_hash", auth.hash_pin("1234"))
