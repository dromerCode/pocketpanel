import subprocess
import sys


def test_qr_prints_a_terminal_code():
    out = subprocess.run([sys.executable, "-m", "app.qr", "https://casa.example.ts.net:8443/#setup/K7P-4QM"],
                         capture_output=True, text=True, check=True).stdout
    lines = [l for l in out.splitlines() if l.strip()]
    assert len(lines) > 10 and any("█" in l or "▀" in l or "▄" in l for l in lines)
    assert len({len(l) for l in lines}) == 1  # cuadrado: todas las filas igual de anchas
