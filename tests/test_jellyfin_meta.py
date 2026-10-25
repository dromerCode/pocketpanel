from app.modules.jellyfin.jellyfin_meta import jfa_id, parse_meta


def test_jfa_id():
    assert jfa_id("192A5964-119F-426C-851B-6712CC500DE4") == "192a5964119f426c851b6712cc500de4"


def test_parse_meta():
    out = "\n".join([
        "AAAA-1|2026-02-13 13:33:16.1769555|2026-02-13 13:40:00|",           # alta conocida, sin foto
        "BBBB-2||2025-12-13 01:15:57.10|2024-10-15 11:53:34.78",              # antigua: la foto es lo más viejo
        "CCCC-3|||",                                                          # nada
        "basura",
    ])
    m = parse_meta(out)
    assert m["aaaa1"] == {"since": 1770989596, "approx": False, "image": False}  # 2026-02-13 13:33:16 UTC
    assert m["bbbb2"]["approx"] is True and m["bbbb2"]["image"] is True
    assert m["bbbb2"]["since"] == 1728993214  # 2024-10-15 11:53:34 UTC
    assert m["cccc3"] == {"since": None, "approx": True, "image": False}
    assert len(m) == 3


def test_meta_command_uses_configured_db():
    from app.modules.jellyfin.jellyfin_meta import meta_command
    c = meta_command("/srv/jf/data/jellyfin.db")
    assert "file:/srv/jf/data/jellyfin.db?mode=ro" in c
