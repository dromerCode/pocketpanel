from app.catalog import CATALOG, GENERAL
from app.config import MODULE_DEFAULTS, TOP_DEFAULTS
from app.modules import MODULES


def test_catalog_covers_every_module_and_option():
    assert list(CATALOG) == MODULES
    for name, entry in CATALOG.items():
        assert entry["title"] and entry["icon"] and entry["desc"], name
        keys = {f["key"] for f in entry["fields"] if f["type"] != "secret"}
        assert keys == set(MODULE_DEFAULTS[name]) - {"enabled"}, name
        for f in entry["fields"]:
            assert f["type"] in ("bool", "str", "int", "time", "list", "choice", "secret") and f["label"], (name, f)


def test_general_fields_exist_in_config():
    assert {f["key"] for f in GENERAL} <= set(TOP_DEFAULTS)
