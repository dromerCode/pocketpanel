"""Dependencias por módulo: se descargan solo si el módulo está activo, una vez, y se borran al apagarlo."""
import asyncio
import importlib
import sys

import pytest

from app import deps as D

FAKE_PIP = """
import sys, pathlib, sysconfig
args = sys.argv[1:]
prefix = args[args.index("--prefix") + 1]
reqs = pathlib.Path(args[args.index("-r") + 1]).read_text()
if "roto" in reqs:
    print("ERROR: No matching distribution found for roto")
    sys.exit(1)
site = pathlib.Path(sysconfig.get_path("purelib", "posix_prefix", vars={"base": prefix, "platbase": prefix}))
(site / "paquete_falso").mkdir(parents=True)
(site / "paquete_falso" / "__init__.py").write_text("VALOR = 42\\n")
print("Successfully installed paquete-falso-1.0")
"""


@pytest.fixture
def mods(tmp_path, monkeypatch):
    root = tmp_path / "modules"
    for name, reqs in {"bolsa": "paquete-falso==1.0\n", "roto": "roto==1.0\n", "simple": None}.items():
        (root / name).mkdir(parents=True)
        if reqs:
            (root / name / "requirements.txt").write_text(reqs)
    monkeypatch.setattr(D, "MODULES_DIR", root)
    pip = tmp_path / "pip.py"
    pip.write_text(FAKE_PIP)
    return D.Deps(str(tmp_path / "data"), pip=[sys.executable, str(pip)])


def test_module_without_requirements_is_always_ready(mods):
    assert not mods.needs("simple") and mods.ready("simple") and mods.view("simple") is None


def test_install_then_import(mods):
    assert not mods.ready("bolsa")
    assert mods.view("bolsa") == {"packages": ["paquete-falso==1.0"], "ready": False, "status": None}
    job = asyncio.run(mods.install("bolsa"))
    assert job.status == "ok", job.lines
    assert mods.ready("bolsa") and mods.view("bolsa")["status"] == "ok"
    assert any("Successfully installed" in line for line in job.lines)
    mods.activate("bolsa")
    try:
        assert importlib.import_module("paquete_falso").VALOR == 42
    finally:
        sys.modules.pop("paquete_falso", None)
        sys.path[:] = [p for p in sys.path if str(mods.root) not in p]


def test_failed_install_leaves_nothing(mods):
    job = asyncio.run(mods.install("roto"))
    assert job.status == "failed"
    assert not mods.ready("roto")
    assert not list(mods.root.iterdir())  # ni la carpeta a medias


def test_prune_frees_disabled_and_old_versions(mods):
    asyncio.run(mods.install("bolsa"))
    old = mods.root / "bolsa-000000000000"
    old.mkdir()
    assert mods.prune(["bolsa"]) == [old.name]
    assert mods.ready("bolsa")
    assert mods.prune([]) == [mods.dir("bolsa").name]  # apagado: fuera
    assert not mods.ready("bolsa")


def test_new_versions_mean_new_download(mods):
    asyncio.run(mods.install("bolsa"))
    (D.MODULES_DIR / "bolsa" / "requirements.txt").write_text("paquete-falso==2.0\n")
    assert not mods.ready("bolsa")
