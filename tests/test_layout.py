import json

from app.layout import load_layout
from tests.test_modules import client


def test_layout_roundtrip(tmp_path):
    c = client(tmp_path, "modules: {}\n")
    assert c.get("/api/layout").json() == {"widgets": []}
    items = [{"id": "stocks", "size": 4}, {"id": "cpu", "size": 3, "hidden": True}, {"id": "cpu", "size": 2}]
    r = c.put("/api/layout", json={"widgets": items})
    assert r.json() == {"widgets": [{"id": "stocks", "size": 4, "hidden": False}, {"id": "cpu", "size": 3, "hidden": True}]}
    assert c.get("/api/layout").json() == r.json()


def test_layout_rejects_junk(tmp_path):
    c = client(tmp_path, "modules: {}\n")
    for bad in [None, "x", [{"id": "cpu", "size": 5}], [{"id": "cpu", "size": 12}], [{"id": "../x", "size": 3}], [{"size": 3}],
                [{"id": f"w{i}", "size": 3} for i in range(101)]]:
        assert c.put("/api/layout", json={"widgets": bad}).status_code == 400
    (tmp_path / "data" / "layout.json").write_text("{roto")
    assert load_layout(str(tmp_path / "data")) == {"widgets": []}
    c.cookies.clear()
    assert c.get("/api/layout").status_code == 401


def test_layout_from_12_columns(tmp_path):
    """Lo guardado con la rejilla de 12 de antes ("status") se lee en columnas de 4, sin tocar el archivo."""
    d = tmp_path / "data"
    d.mkdir()
    old = {"status": [{"id": "cpu", "size": 3}, {"id": "disks", "size": 4}, {"id": "history", "size": 8},
                      {"id": "procs", "size": 12}, {"id": "actions", "size": 6, "hidden": True}]}
    (d / "layout.json").write_text(json.dumps(old))
    assert load_layout(str(d)) == {"widgets": [
        {"id": "cpu", "size": 1, "hidden": False}, {"id": "disks", "size": 1, "hidden": False},
        {"id": "history", "size": 3, "hidden": False}, {"id": "procs", "size": 4, "hidden": False},
        {"id": "actions", "size": 2, "hidden": True}]}


def test_version(tmp_path):
    c = client(tmp_path, "modules: {}\n")
    v = c.get("/api/version").json()["v"]
    assert len(v) == 12 and f'data-v="{v}"' in c.get("/").text
