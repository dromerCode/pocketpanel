"""Gráfica de precio en PNG para Telegram sin matplotlib: línea, área, zona de entrada y precio de compra.

Sin texto (el título y el precio van en el pie de la foto). Se dibuja al doble de tamaño y se reduce para suavizar
los bordes."""
import struct
import zlib

BG = (11, 15, 20)
GRID = (35, 44, 56)
ZONE = (79, 140, 255)
ENTRY = (139, 152, 165)
UP, DOWN = (63, 185, 80), (248, 81, 73)
S = 2  # superresolución


def _png(w: int, h: int, rows: list[bytes]) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _mix(a, b, alpha):
    return tuple(round(x + (y - x) * alpha) for x, y in zip(a, b))


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = bytearray(bytes(BG) * (w * h))

    def get(self, x, y):
        i = (y * self.w + x) * 3
        return tuple(self.px[i:i + 3])

    def set(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i:i + 3] = bytes(c)

    def hband(self, y0, y1, c):
        y0, y1 = max(0, int(y0)), min(self.h, int(y1) + 1)
        row = bytes(c) * self.w
        for y in range(y0, y1):
            self.px[y * self.w * 3:(y + 1) * self.w * 3] = row

    def blend_column(self, x, y0, c, alpha):
        for y in range(max(0, int(y0)), self.h):
            self.set(x, y, _mix(self.get(x, y), c, alpha))

    def disk(self, cx, cy, r, c):
        ir = int(r) + 1
        for dy in range(-ir, ir + 1):
            for dx in range(-ir, ir + 1):
                if dx * dx + dy * dy <= r * r:
                    self.set(int(cx + dx), int(cy + dy), c)

    def line(self, pts, r, c, dash=0):
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            n = max(1, int(max(abs(x1 - x0), abs(y1 - y0))))
            for i in range(n + 1):
                if dash and (i // dash) % 2:
                    continue
                t = i / n
                self.disk(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, r, c)

    def shrink(self) -> bytes:
        w, h = self.w // S, self.h // S
        rows = []
        for y in range(h):
            row = bytearray()
            for x in range(w):
                acc = [0, 0, 0]
                for dy in range(S):
                    for dx in range(S):
                        p = self.get(x * S + dx, y * S + dy)
                        acc[0] += p[0]; acc[1] += p[1]; acc[2] += p[2]  # noqa: E702
                row += bytes(v // (S * S) for v in acc)
            rows.append(bytes(row))
        return _png(w, h, rows)


def price_chart(values: list[float], zone: list[float] | None = None, entry: float | None = None,
                w: int = 640, h: int = 320) -> bytes | None:
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return None
    W, H, pad = w * S, h * S, 16 * S
    bounds = values + (list(zone) if zone else []) + ([entry] if entry else [])
    lo, hi = min(bounds), max(bounds)
    margin = max((hi - lo) * 0.08, hi * 0.01)
    lo, hi = lo - margin, hi + margin
    x = lambda i: pad + i * (W - 2 * pad) / (len(values) - 1)  # noqa: E731
    y = lambda v: H - pad - (v - lo) / (hi - lo) * (H - 2 * pad)  # noqa: E731
    c = Canvas(W, H)
    if zone:
        c.hband(y(max(zone)), y(min(zone)), _mix(BG, ZONE, 0.18))
    for k in range(1, 4):
        c.hband(pad + k * (H - 2 * pad) / 4, pad + k * (H - 2 * pad) / 4 + S - 1, GRID)
    color = UP if values[-1] >= values[0] else DOWN
    pts = [(x(i), y(v)) for i, v in enumerate(values)]
    for px in range(int(pts[0][0]), int(pts[-1][0]) + 1):  # área bajo la línea
        i = min(len(values) - 2, int((px - pad) / ((W - 2 * pad) / (len(values) - 1))))
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        t = (px - x0) / (x1 - x0) if x1 != x0 else 0
        c.blend_column(px, y0 + (y1 - y0) * t, color, 0.12)
    if entry:
        c.line([(pad, y(entry)), (W - pad, y(entry))], 0.8 * S, ENTRY, dash=6 * S)
    c.line(pts, 1.1 * S, color)
    return c.shrink()
