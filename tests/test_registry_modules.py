"""El sistema de módulos: cada carpeta de app/modules es un módulo completo y se carga solo si está activo."""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import ConfigError, load_config
from app.module import Module, field
from app.modules import MODULES, REGISTRY, load_order, web_dir
from tests.test_modules import ALL, NONE, client

MODS = Path(__file__).parent.parent / "app" / "modules"


@pytest.mark.parametrize("name", MODULES)
def test_every_module_folder_is_complete(name):
    m = REGISTRY[name]
    assert m.name == name and m.title and m.icon and m.desc
    assert callable(importlib.import_module(f"app.modules.{name}.api").setup)
    assert web_dir(name) == MODS / name / "web"


def test_every_folder_is_registered():
    folders = {p.name for p in MODS.iterdir() if (p / "__init__.py").is_file()}
    assert folders == set(MODULES)


def test_manifests_dont_import_module_code():
    # La tienda lee todos los manifiestos; el código de un módulo (api.py y lo suyo) solo se importa si está activo
    out = subprocess.run([sys.executable, "-c", "import sys, app.modules; print(sorted(k for k in sys.modules "
                          "if k.startswith('app.modules.') and k.count('.') > 2))"],
                         cwd=MODS.parent.parent, capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


def test_load_order_follows_after():
    order = load_order()
    assert order.index("backups") < order.index("updates")
    assert sorted(order) == sorted(MODULES)


def test_defaults_come_from_fields():
    m = Module(icon="x", title="t", desc="d", fields=[
        field("a", "A"), field("n", "N", "int", default=3), field("l", "L", "list"), field("k", "K", "secret"),
        field("on", "On", "bool")])
    assert m.defaults() == {"enabled": False, "a": "", "n": 3, "l": [], "on": False}
    assert m.secret_keys() == {"k"}
    with pytest.raises(ValueError):
        field("x", "X", "fecha")


@pytest.mark.parametrize("yml, err", [
    ("modules: {backups: {enabled: true, dest: 'a@b:/c'}}", "modules.backups.source: obligatorio"),
    ("modules: {claude: {enabled: true, permission_mode: yolo}}", "modules.claude.permission_mode: tiene que ser uno de"),
    ("modules: {updates: {enabled: true, check_at: '25:00'}}", "modules.updates.check_at: hora no válida"),
    ("modules: {sites: {enabled: true, interval: 'cinco'}}", "modules.sites.interval: tipo no válido"),
    ("modules: {raid: {enabled: true, disco: /dev/md0}}", "modules.raid.disco: opción desconocida"),
])
def test_validation_comes_from_manifest(tmp_path, yml, err):
    p = tmp_path / "config.yml"
    p.write_text(yml)
    with pytest.raises(ConfigError, match=err):
        load_config(str(p), {"PANEL_DATA": str(tmp_path)})


def test_nullable_time(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text("modules: {claude: {enabled: true, report_at: null}}")
    assert load_config(str(p), {"PANEL_DATA": str(tmp_path)}).mod("claude")["report_at"] is None


def test_web_served_only_for_enabled_modules(tmp_path):
    (tmp_path / "on").mkdir()
    (tmp_path / "off").mkdir()
    on = client(tmp_path / "on", ALL)
    assert on.get("/modules/raid/index.js").status_code == 200
    assert on.get("/modules/raid/card.html").status_code == 200
    assert "ui" in on.get("/api/me").json() and "raid" in on.get("/api/me").json()["ui"]
    off = client(tmp_path / "off", NONE)
    assert off.get("/modules/raid/index.js").status_code == 404
    assert off.get("/modules/terminal/index.js").status_code == 404


def test_core_page_has_no_module_markup():
    # Lo de cada módulo vive en su carpeta: index.html no sabe nada de ellos
    html = (Path(__file__).parent.parent / "web" / "index.html").read_text()
    for gone in ("view-terminal", "view-claude", "view-users", "view-downloads", 'id="raid"', 'id="backup"',
                 "xterm", "marked", "dompurify", "data-module="):
        assert gone not in html, gone
