"""Pinta un QR en la terminal (lo usa install.sh para abrir el asistente desde el móvil).

    python -m app.qr https://…
"""
import sys

import qrcode


def render(text: str) -> str:
    q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_L)
    q.add_data(text)
    q.make(fit=True)
    m = q.get_matrix()
    if len(m) % 2:
        m.append([False] * len(m[0]))
    # Dos filas por línea con medios bloques; claro sobre oscuro para que se lea en terminales negras
    chars = {(False, False): "█", (False, True): "▀", (True, False): "▄", (True, True): " "}
    return "\n".join("".join(chars[(m[y][x], m[y + 1][x])] for x in range(len(m[0])))
                     for y in range(0, len(m), 2))


if __name__ == "__main__":
    print(render(sys.argv[1]))
