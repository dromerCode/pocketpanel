from app.layout import load_layout
from tests.test_modules import client


def test_layout_roundtrip(tmp_path):
    c = client(tmp_path, "modules: {}\n")
    assert c.get("/api/layout").json() == {"status": []}
    items = [{"id": "stocks", "size": 4}, {"id": "cpu", "size": 1, "hidden": True}, {"id": "cpu", "size": 2}]
    r = c.put("/api/layout", json={"status": items})
    assert r.json() == {"status": [{"id": "stocks", "size": 4, "hidden": False}, {"id": "cpu", "size": 1, "hidden": True}]}
    assert c.get("/api/layout").json() == r.json()


def test_layout_rejects_junk(tmp_path):
    c = client(tmp_path, "modules: {}\n")
    for bad in [None, "x", [{"id": "cpu", "size": 5}], [{"id": "cpu", "size": 12}], [{"id": "../x", "size": 3}], [{"size": 3}],
                [{"id": f"w{i}", "size": 3} for i in range(101)]]:
        assert c.put("/api/layout", json={"status": bad}).status_code == 400
    (tmp_path / "data" / "layout.json").write_text("{roto")
    assert load_layout(str(tmp_path / "data")) == {"status": []}
    c.cookies.clear()
    assert c.get("/api/layout").status_code == 401


def test_old_12_column_layout_is_migrated(tmp_path):
    import json
    d = tmp_path / "data"
    d.mkdir()
    (d / "layout.json").write_text(json.dumps({"status": [{"id": "cpu", "size": 3}, {"id": "disks", "size": 4},
                                                          {"id": "history", "size": 8}, {"id": "x", "size": 12}]}))
    assert [it["size"] for it in load_layout(str(d))["status"]] == [1, 1, 3, 4]
