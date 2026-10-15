"""El repo es público: nada del servidor de su autor (rutas, dominios, IPs, nombres)."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
FORBIDDEN = re.compile(r"/DATA\b|AppData|[Pp]ichahouse|tail41f6d6|[Pp]ichaserver|[Pp]ichaflix|HDDRaid|192\.168\.|"
                       r"dev-disk-by-uuid|\b[Oo][Mm][Vv]\b|\b[Pp]icha\b|[Zz]ima[Oo][Ss]|[Cc]asa[Oo][Ss]")


def tracked_files():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / f for f in out if (ROOT / f).is_file() and not f.endswith((".png", ".svg"))]


def test_no_personal_data():
    hits = []
    for f in tracked_files():
        if f.name == "test_no_personal.py":
            continue
        for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
            if FORBIDDEN.search(line):
                hits.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()[:100]}")
    assert not hits, "\n".join(hits)
