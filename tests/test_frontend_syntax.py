import shutil
import subprocess
from pathlib import Path

import pytest

JS = sorted((Path(__file__).parent.parent / "web" / "js").glob("*.js"))


@pytest.mark.skipif(not shutil.which("node"), reason="sin node")
@pytest.mark.parametrize("path", JS, ids=lambda p: p.name)
def test_js_module_parses(path):
    # Como módulo ES: detecta, p. ej., un import que choca con una función del mismo nombre
    r = subprocess.run(["node", "--input-type=module", "--check"], input=path.read_text(), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
