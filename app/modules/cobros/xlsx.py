"""Rellena una copia de tu plantilla de factura (.xlsx) con los datos de una factura apuntada.

Solo cambia el valor de las celdas que dice la pestaña «Instrucciones» de la plantilla (número, fecha, cliente,
líneas, forma de pago y los tipos de IVA y retención); el diseño, las fórmulas y lo demás se quedan como están.
Se escribe también el resultado de las fórmulas (y se pide recalcular al abrir) para que se vea bien en cualquier
programa. Sin librerías: un .xlsx es un zip con XML."""
import io
import os
import re
import zipfile
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from xml.sax.saxutils import escape

SHEET, INFO = "Factura", "Instrucciones"
LINES = range(18, 22)  # A18:C21, cuatro líneas
NEEDED = {SHEET: ["D1", "D2", "A12", "A13", "A14", "A15", "D23", "C24", "D24", "C25", "D25", "D26", "A30",
                  *(f"{c}{r}" for r in LINES for c in "ABCD")],
          INFO: ["B15", "B16"]}


class TemplateError(ValueError):
    pass


def _cents(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), ROUND_HALF_UP)


def round2(v) -> float:
    """A dos decimales, los medios hacia arriba: como REDONDEAR en la plantilla (el round() de Python no)."""
    return float(_cents(Decimal(str(v))))


def line_amount(qty, price) -> float:
    return float(_cents(Decimal(str(qty)) * Decimal(str(price))))


def amounts(base, iva, irpf) -> tuple[float, float, float]:
    """(IVA, retención, total) de una base: las mismas cuentas en la app y en la factura."""
    b = Decimal(str(base))
    tax, ret = (_cents(b * Decimal(str(r)) / 100) for r in (iva, irpf))
    return float(tax), float(ret), float(_cents(b + tax - ret))


def write_private(path: Path, blob: bytes) -> None:
    """A un temporal (solo lo lee el panel) y se cambia de golpe: un corte a medias no deja el archivo roto."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)


def _sheets(z: zipfile.ZipFile) -> dict[str, str]:
    """Nombre de la pestaña → ruta de su XML dentro del zip."""
    wb = z.read("xl/workbook.xml").decode()
    rels = z.read("xl/_rels/workbook.xml.rels").decode()
    targets = {m.group(1): m.group(2) for m in re.finditer(r'<Relationship [^>]*?Id="([^"]+)"[^>]*?Target="([^"]+)"', rels)}
    targets |= {m.group(2): m.group(1) for m in re.finditer(r'<Relationship [^>]*?Target="([^"]+)"[^>]*?Id="([^"]+)"', rels)}
    out = {}
    for m in re.finditer(r'<sheet [^>]*?name="([^"]+)"[^>]*?r:id="([^"]+)"', wb):
        t = targets.get(m.group(2), "")
        out[m.group(1)] = t.lstrip("/") if t.startswith("/") else f"xl/{t}"
    return out


def _cell_re(ref: str):
    return re.compile(rf'<c r="{ref}"(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</c>)', re.S)


class _Sheet:
    def __init__(self, xml: str, name: str):
        self.xml, self.name = xml, name

    def _find(self, ref):
        m = _cell_re(ref).search(self.xml)
        if not m:
            raise TemplateError(f"La plantilla no tiene la celda {self.name}!{ref}: ¿le has cambiado el diseño?")
        return m

    def _put(self, m, ref, inner, t=None):
        s = re.search(r'\bs="(\d+)"', m.group("attrs") or "")
        attrs = f' s="{s.group(1)}"' if s else ""
        attrs += f' t="{t}"' if t else ""
        cell = f'<c r="{ref}"{attrs}>{inner}</c>' if inner else f'<c r="{ref}"{attrs}/>'
        self.xml = self.xml[:m.start()] + cell + self.xml[m.end():]

    def text(self, ref, value: str):
        m = self._find(ref)
        if value:
            self._put(m, ref, f'<is><t xml:space="preserve">{escape(value)}</t></is>', "inlineStr")
        else:
            self._put(m, ref, "")

    def number(self, ref, value):
        m = self._find(ref)
        self._put(m, ref, "" if value is None else f"<v>{_num(value)}</v>", "n" if value is not None else None)

    def result(self, ref, value):
        """Una celda con fórmula: se deja la fórmula y se cambia solo el resultado guardado."""
        m = self._find(ref)
        f = re.search(r"<f[^>]*?(?:/>|>.*?</f>)", m.group("body") or "", re.S)
        f = f.group(0) if f else ""
        if isinstance(value, str):
            self._put(m, ref, f"{f}<v>{escape(value)}</v>", "str")
        else:
            self._put(m, ref, f"{f}<v>{_num(value)}</v>", "n")


def _num(v) -> str:
    v = float(v)
    return str(int(v)) if v.is_integer() else repr(v)


def _pct(v: float) -> str:
    return f"{v:g}"


def check(blob: bytes) -> None:
    """¿Sirve como plantilla? (para no guardar cualquier cosa al subirla)"""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            sheets = _sheets(z)
            for name, refs in NEEDED.items():
                if name not in sheets:
                    raise TemplateError(f"La plantilla tiene que tener una pestaña «{name}»")
                sh = _Sheet(z.read(sheets[name]).decode(), name)
                for ref in refs:
                    sh._find(ref)
    except (zipfile.BadZipFile, KeyError):
        raise TemplateError("Eso no es un .xlsx") from None


def fill(blob: bytes, inv: dict, client: dict, base: float, iva: float, irpf: float) -> bytes:
    """`inv`: {number, date, lines: [{concept, qty, price}], pay_text}; `client`: {name, nif, address, city}."""
    src = zipfile.ZipFile(io.BytesIO(blob))
    sheets = _sheets(src)
    for name in NEEDED:
        if name not in sheets:
            raise TemplateError(f"La plantilla tiene que tener una pestaña «{name}»")
    f = _Sheet(src.read(sheets[SHEET]).decode(), SHEET)
    info = _Sheet(src.read(sheets[INFO]).decode(), INFO)

    f.text("D1", inv["number"])
    f.number("D2", (date.fromisoformat(inv["date"]) - date(1899, 12, 30)).days)
    nif = client.get("nif", "")
    for ref, v in zip(("A12", "A13", "A14", "A15"),
                      (client.get("name", ""), f"NIF {nif}" if nif else "", client.get("address", ""), client.get("city", ""))):
        f.text(ref, v)
    lines = inv["lines"]
    for i, r in enumerate(LINES):
        ln = lines[i] if i < len(lines) else None
        f.text(f"A{r}", ln["concept"] if ln else "")
        f.number(f"B{r}", ln["qty"] if ln else None)
        f.number(f"C{r}", ln["price"] if ln else None)
        f.result(f"D{r}", line_amount(ln["qty"], ln["price"]) if ln else "")
    tax, ret, due = amounts(base, iva, irpf)
    f.result("D23", base)
    f.result("C24", f"IVA {_pct(iva)} %")
    f.result("D24", tax)
    f.result("C25", f"Retención IRPF {_pct(irpf)} %")
    f.result("D25", -ret)
    f.result("D26", due)
    if inv.get("pay_text"):
        f.text("A30", inv["pay_text"])
    info.number("B15", round(iva / 100, 4))
    info.number("B16", round(irpf / 100, 4))

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == sheets[SHEET]:
                data = f.xml.encode()
            elif item.filename == sheets[INFO]:
                data = info.xml.encode()
            elif item.filename == "xl/workbook.xml":  # que Excel/LibreOffice lo recalcule al abrir
                data = re.sub(rb"<calcPr(?![^>]*fullCalcOnLoad)", b'<calcPr fullCalcOnLoad="1"', data)
            dst.writestr(item, data)
    return out.getvalue()
