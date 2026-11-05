"""Los datos de Cobros: un JSON en data/cobros/cobros.json (solo lo lee el panel: 600).

  products  tus programas, cada uno con sus planes (precio sin IVA y cada cuánto se cobra)
  clients   a quién facturas (NIF, dirección… lo que sale en la factura) y su retención de IRPF
  subs      qué plan tiene cada cliente: desde cuándo, gratis hasta cuándo y si se dio de baja
  charges   lo que te tienen que pagar: las cuotas que salen solas de las suscripciones, los encargos (una web,
            con pagos a plazos) y los apuntes sueltos (alguien que te debe algo). Cada uno con sus cobros y,
            si la tiene, los datos de su factura.
  annulled  los números de factura que se quitaron: no se vuelven a ofrecer, y queda constancia de cada uno

Cada factura hecha se guarda rellena en data/cobros/facturas/<año>/ (una vez hecha no se vuelve a tocar, aunque
cambies la plantilla o los datos del cliente).

Los importes van sin IVA (`base`); lo que te pagan es base + IVA − retención, como en la plantilla."""
import calendar
import json
import re
import secrets
from datetime import date, timedelta
from pathlib import Path

from .xlsx import amounts, fill, line_amount, round2, write_private

PERIODS = {"month": 1, "quarter": 3, "year": 12}
METHODS = ("transferencia", "efectivo", "bizum", "tarjeta", "otro")
PAID_AS = {"transferencia": "Pagada por transferencia", "efectivo": "Pagada en efectivo", "bizum": "Pagada por Bizum",
           "tarjeta": "Pagada con tarjeta", "otro": "Pagada"}
MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre")
KINDS = ("products", "clients", "subs", "charges")
TERMS = ("client", "product", "plan", "price")  # si cambian, las cuotas sin cobrar se vuelven a sacar


class CobrosError(ValueError):
    """Algo que no se puede hacer (un 400/409 con su motivo)."""


def new_id() -> str:
    return secrets.token_hex(4)


def money(v, what="importe", allow_negative=False) -> float:
    """«12,50», «12.5» o 12.5 → 12.5; «1.234» son miles, como se escribe aquí (un 1.234 de JSON, no)."""
    if isinstance(v, bool):
        raise CobrosError(f"{what}: no es un número")
    if isinstance(v, str):
        v = v.strip().replace("€", "").replace(" ", "")
        if "," in v:
            v = v.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"-?[1-9]\d{0,2}(\.\d{3})+", v):
            v = v.replace(".", "")
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise CobrosError(f"{what}: no es un número") from None
    if n != n or abs(n) > 1e9 or (n < 0 and not allow_negative):
        raise CobrosError(f"{what}: fuera de rango")
    return round2(n)


def day(v, what="fecha", optional=False) -> str | None:
    if v in (None, "") and optional:
        return None
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise CobrosError(f"{what}: tiene que ser una fecha (AAAA-MM-DD)") from None


def text(v, n=200) -> str:
    return str(v or "").strip()[:n]


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def total(c: dict) -> float:
    """Lo que hay que cobrar: base + IVA − retención (redondeados como en la plantilla)."""
    return amounts(c["base"], c["iva"], c["irpf"])[2]


def paid(c: dict) -> float:
    return round(sum(p["amount"] for p in c["payments"]), 2)


def covered(spans: list, a: date, b: date) -> bool:
    """¿Algún periodo ya sacado pisa el de a a b? (si la suscripción cambió, no empiezan el mismo día)"""
    return any(x <= b.isoformat() and a.isoformat() <= y for x, y in spans)


class Store:
    def __init__(self, data_dir: str, settings=lambda: {}):
        self.dir = Path(data_dir) / "cobros"
        self.path = self.dir / "cobros.json"
        self.template = self.dir / "plantilla.xlsx"
        self.invoices = self.dir / "facturas"
        self.settings = settings  # el bloque de config.yml del módulo (cambia al guardar sus ajustes)

    # ---------- disco ----------

    def load(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
        except FileNotFoundError:
            d = {}
        except ValueError as e:
            raise CobrosError(f"{self.path} está roto: {e}") from None
        for k in KINDS:
            d.setdefault(k, [])
        d.setdefault("annulled", [])
        for c in d["charges"]:  # los guardados antes de existir `taxes`
            c.setdefault("taxes", bool(c["iva"] or c["irpf"] or c["invoice"]))
        return d

    def save(self, d: dict) -> None:
        """A un temporal y se cambia de golpe: un corte a medias no deja el JSON roto."""
        write_private(self.path, json.dumps(d, indent=1, ensure_ascii=False).encode())

    def save_template(self, blob: bytes) -> None:
        write_private(self.template, blob)

    # ---------- ajustes ----------

    def opt(self, key, default):
        v = self.settings().get(key)
        if key in ("iva", "irpf"):
            try:
                return money(v, key)
            except CobrosError:
                return default
        return default if v in (None, "") else v

    def iva(self) -> float:
        return self.opt("iva", 21.0)

    def due_days(self) -> int:
        return int(self.opt("due_days", 15))

    # ---------- cuotas de las suscripciones ----------

    @staticmethod
    def plan_of(d: dict, s: dict) -> tuple[dict | None, dict | None]:
        prod = next((p for p in d["products"] if p["id"] == s["product"]), None)
        return prod, next((p for p in (prod or {}).get("plans", []) if p["id"] == s["plan"]), None)

    @staticmethod
    def periods(s: dict, plan: dict):
        """Los periodos que se cobran (inicio, fin), sin los meses gratis, los borrados ni los de después de la baja."""
        start, step = date.fromisoformat(s["start"]), PERIODS[plan["period"]]
        free = s.get("free_until")
        for k in range(1200):
            a = add_months(start, k * step)
            if s.get("end") and a.isoformat() >= s["end"]:
                return
            if (free and a.isoformat() < free) or a.isoformat() in s.get("skip", []):
                continue
            yield a, add_months(start, (k + 1) * step) - timedelta(days=1)

    def sync(self, d: dict, today: date) -> list[dict]:
        """Saca las cuotas que ya tocan (hasta `lead_days` antes de que empiece el periodo). Devuelve las nuevas."""
        limit = today + timedelta(days=int(self.opt("lead_days", 7)))
        spans: dict[str, list] = {}
        for c in d["charges"]:
            if c.get("sub") and c.get("period"):
                spans.setdefault(c["sub"], []).append(c["period"])
        clients = {c["id"]: c for c in d["clients"]}
        new = []
        for s in d["subs"]:
            prod, plan = self.plan_of(d, s)
            cl = clients.get(s["client"])
            if not plan or not cl:
                continue
            for a, b in self.periods(s, plan):
                if a > limit:
                    break
                if covered(spans.get(s["id"], []), a, b):
                    continue
                c = {"id": new_id(), "client": cl["id"], "who": "", "sub": s["id"],
                     "concept": f"Suscripción {ADJ[plan['period']]} a {prod['name']}, {plan_label(plan['name'])}",
                     "period": [a.isoformat(), b.isoformat()], "date": a.isoformat(), "due": None,
                     "base": s["price"] if s.get("price") is not None else plan["price"],
                     "iva": self.iva(), "irpf": cl.get("irpf", 0.0), "taxes": True, "payments": [], "invoice": None,
                     "notes": "", "alerted": []}
                d["charges"].append(c)
                new.append(c)
        return new

    def _reconcile(self, d: dict, s: dict, old: dict) -> None:
        """Tras cambiar una suscripción: fuera las cuotas sin cobrar ni facturar que ya no tocan (o con otras
        condiciones; sync saca las nuevas). Lo cobrado o facturado se queda y sync no vuelve a cobrar esos días."""
        _, plan = self.plan_of(d, s)
        if not plan:
            return
        valid = {(a.isoformat(), b.isoformat()) for a, b in self.periods(s, plan)}
        same = all(s.get(k) == old.get(k) for k in TERMS)
        d["charges"] = [c for c in d["charges"] if c.get("sub") != s["id"] or c["payments"] or c["invoice"]
                        or (same and tuple(c["period"]) in valid)]

    # ---------- altas y cambios ----------

    def upsert(self, d: dict, kind: str, body: dict, today: date) -> dict:
        if kind not in KINDS:
            raise CobrosError("tipo desconocido")
        items = d[kind]
        old = next((x for x in items if x["id"] == body.get("id")), None) if body.get("id") else None
        item = getattr(self, f"_clean_{kind}")(d, body, old, today)
        item["id"] = old["id"] if old else new_id()
        if old:
            items[items.index(old)] = item
        else:
            items.append(item)
        if old and kind == "subs":
            self._reconcile(d, item, old)
        if old and kind == "products":
            before = {p["id"]: p["period"] for p in old["plans"]}
            moved = {p["id"] for p in item["plans"] if before.get(p["id"], p["period"]) != p["period"]}
            for s in d["subs"]:
                if s["product"] == old["id"] and s["plan"] in moved:
                    self._reconcile(d, s, s)
        return item

    def _clean_products(self, d, b, old, today):
        name = text(b.get("name"), 80)
        if not name:
            raise CobrosError("Falta el nombre del programa")
        plans = []
        for p in b.get("plans") or []:
            pname = text(p.get("name"), 60)
            if not pname:
                raise CobrosError("Cada plan necesita un nombre")
            if p.get("period") not in PERIODS:
                raise CobrosError(f"{pname}: ¿cada cuánto se cobra?")
            plans.append({"id": p.get("id") or new_id(), "name": pname, "period": p["period"],
                          "price": money(p.get("price"), f"precio de {pname}")})
        if old:
            gone = {p["id"] for p in old["plans"]} - {p["id"] for p in plans}
            if any(s["product"] == old["id"] and s["plan"] in gone for s in d["subs"]):
                raise CobrosError("Hay clientes con ese plan: cámbiales el plan antes de quitarlo")
        return {"name": name, "plans": plans}

    def _clean_clients(self, d, b, old, today):
        name = text(b.get("name"), 120)
        if not name:
            raise CobrosError("Falta el nombre del cliente")
        irpf = money(b.get("irpf", self.opt("irpf", 7.0)), "retención")
        if irpf > 50:
            raise CobrosError("retención: fuera de rango")
        return {"name": name, "nif": text(b.get("nif"), 20).upper(), "address": text(b.get("address"), 120),
                "city": text(b.get("city"), 120), "email": text(b.get("email"), 120),
                "phone": text(b.get("phone"), 40), "irpf": irpf, "notes": text(b.get("notes"), 2000)}

    def _clean_subs(self, d, b, old, today):
        if not any(c["id"] == b.get("client") for c in d["clients"]):
            raise CobrosError("Ese cliente no existe")
        prod = next((p for p in d["products"] if p["id"] == b.get("product")), None)
        if not prod or not any(p["id"] == b.get("plan") for p in prod["plans"]):
            raise CobrosError("Elige un programa y uno de sus planes")
        start = day(b.get("start"), "primera cuota")
        free = day(b.get("free_until"), "gratis hasta", optional=True)
        end = day(b.get("end"), "baja", optional=True)
        if end and end <= start:
            raise CobrosError("La baja tiene que ser después de la primera cuota")
        price = None if b.get("price") in (None, "") else money(b.get("price"), "precio")
        return {"client": b["client"], "product": prod["id"], "plan": b["plan"], "price": price, "start": start,
                "free_until": free, "end": end, "notes": text(b.get("notes"), 2000),
                "skip": (old or {}).get("skip", [])}

    def _clean_charges(self, d, b, old, today):
        client = b.get("client") or None
        cl = next((c for c in d["clients"] if c["id"] == client), None)
        if client and not cl:
            raise CobrosError("Ese cliente no existe")
        who = "" if cl else text(b.get("who"), 120)
        if not cl and not who:
            raise CobrosError("¿Quién te lo debe?")
        concept = text(b.get("concept"), 300)
        if not concept and cl:  # a un cliente se le factura: hace falta; un apunte suelto puede ir sin él
            raise CobrosError("Falta el concepto")
        keep = old or {}
        taxes = bool(b.get("taxes", keep.get("taxes", cl is not None)))  # un apunte suelto (un amigo…) va sin IVA
        had = keep.get("taxes")  # al editar, sus tipos se quedan salvo que se pidan otros (o cambie de cliente)
        iva = money(b.get("iva", keep["iva"] if had else self.iva()), "IVA") if taxes else 0.0
        default = keep["irpf"] if had and keep["client"] == client else cl.get("irpf", 0) if cl else 0
        irpf = money(b.get("irpf", default), "retención") if taxes else 0.0
        base = money(b.get("base"))
        if keep.get("invoice") and (keep["client"], keep["base"], keep["iva"], keep["irpf"]) != (client, base, iva, irpf):
            raise CobrosError("Ya tiene factura: quítala antes de cambiar el cliente, el importe o los impuestos")
        return {"client": client, "who": who, "sub": keep.get("sub"), "period": keep.get("period"),
                "concept": concept, "date": day(b.get("date") or today.isoformat()),
                "due": day(b.get("due"), "vence", optional=True), "base": base,
                "iva": iva, "irpf": irpf, "taxes": taxes, "payments": keep.get("payments", []), "invoice": keep.get("invoice"),
                "notes": text(b.get("notes"), 2000), "alerted": keep.get("alerted", [])}

    def delete(self, d: dict, kind: str, id_: str) -> None:
        if kind not in KINDS:
            raise CobrosError("tipo desconocido")
        items = d[kind]
        item = next((x for x in items if x["id"] == id_), None)
        if not item:
            raise CobrosError("No existe")
        if kind == "products" and any(s["product"] == id_ for s in d["subs"]):
            raise CobrosError("Hay clientes con este programa: quítales la suscripción antes")
        if kind == "clients":
            if any(c["client"] == id_ and c["invoice"] for c in d["charges"]):
                raise CobrosError("Tiene facturas: no se puede borrar (las facturas hay que guardarlas)")
            d["subs"] = [s for s in d["subs"] if s["client"] != id_]
            d["charges"] = [c for c in d["charges"] if c["client"] != id_]
        if kind == "subs":  # sus cuotas ya cobradas o facturadas se quedan; las demás se van con ella
            d["charges"] = [c for c in d["charges"] if c.get("sub") != id_ or c["payments"] or c["invoice"]]
        if kind == "charges":
            if item["invoice"]:
                raise CobrosError("Tiene factura: quítala antes (su número queda anulado)")
            if item.get("sub"):  # que no vuelva a salir sola
                s = next((s for s in d["subs"] if s["id"] == item["sub"]), None)
                if s:
                    s.setdefault("skip", []).append(item["period"][0])
        items.remove(item)

    # ---------- cobros y facturas ----------

    def charge(self, d: dict, id_: str) -> dict:
        c = next((c for c in d["charges"] if c["id"] == id_), None)
        if not c:
            raise CobrosError("No existe")
        return c

    def pay(self, c: dict, b: dict, today: date) -> None:
        amount = money(b.get("amount"), "importe cobrado")
        if amount <= 0:
            raise CobrosError("¿Cuánto te han pagado?")
        method = b.get("method") or "transferencia"
        if method not in METHODS:
            raise CobrosError("forma de pago desconocida")
        left = round(total(c) - paid(c), 2)
        if amount > left:  # también para un doble toque: el segundo ya no cabe
            raise CobrosError(f"Solo queda por cobrar {left:.2f} €".replace(".", ","))
        c["payments"].append({"date": day(b.get("date") or today.isoformat()), "amount": amount, "method": method})

    def unpay(self, d: dict, c: dict, i: int, today: date, expect: dict | None = None) -> None:
        """Si deja de estar pagado, su factura automática (dice «Pagada») se va; volverá con su número al cobrar.
        `expect` ({date, amount}, el que se ve en pantalla): si en esa posición ya hay otro (otra pestaña), no se toca."""
        if not 0 <= i < len(c["payments"]):
            raise CobrosError("Ese cobro ya no existe: recarga")
        p = c["payments"][i]
        if expect:
            try:
                amount = round2(float(expect.get("amount")))
            except (TypeError, ValueError, ArithmeticError):
                amount = None
            if (expect.get("date"), amount) != (p["date"], p["amount"]):
                raise CobrosError("Ese cobro ha cambiado: recarga")
        c["payments"].pop(i)
        if (c["invoice"] or {}).get("auto") and round(total(c) - paid(c), 2) > 0:
            self.uninvoice(d, c, today, reusable=True)

    def uninvoice(self, d: dict, c: dict, today: date, reusable: bool = False) -> None:
        """Quita la factura y deja constancia de su número (no se vuelve a ofrecer). `reusable`: su cargo lo recupera."""
        if not c["invoice"]:
            raise CobrosError("No tiene factura")
        cl = next((x for x in d["clients"] if x["id"] == c["client"]), {"name": c["who"]})
        d["annulled"].append({"number": c["invoice"]["number"], "date": c["invoice"]["date"], "client": cl["name"],
                              "charge": c["id"], "removed": today.isoformat(), "reusable": reusable})
        self.drop_invoice(c)
        c["invoice"] = None

    def invoice(self, d: dict, c: dict, b: dict) -> None:
        number = text(b.get("number"), 30)
        if not number:
            raise CobrosError("Falta el número de factura")
        if any(x["invoice"] and x["invoice"]["number"] == number and x is not c for x in d["charges"]):
            raise CobrosError(f"Ya hay otra factura con el número {number}")
        lines = []
        for ln in b.get("lines") or []:
            if not text(ln.get("concept"), 400):
                continue
            lines.append({"concept": text(ln["concept"], 400), "qty": money(ln.get("qty", 1), "cantidad"),
                          "price": money(ln.get("price"), "precio", allow_negative=True)})
        if not 1 <= len(lines) <= 4:
            raise CobrosError("La factura lleva de 1 a 4 líneas (las que caben en la plantilla)")
        c["base"] = round2(sum(line_amount(x["qty"], x["price"]) for x in lines))
        if "iva" in b:
            c["iva"] = money(b["iva"], "IVA")
        if "irpf" in b:
            c["irpf"] = money(b["irpf"], "retención")
        c["taxes"] = True
        d["annulled"] = [a for a in d["annulled"] if a["number"] != number]
        c["invoice"] = {"number": number, "date": day(b.get("date"), "fecha de la factura"), "lines": lines,
                        "pay_text": text(b.get("pay_text"), 200), "file": (c["invoice"] or {}).get("file")}

    # ---------- la carpeta de facturas ----------

    def invoice_file(self, d: dict, c: dict) -> Path | None:
        """El .xlsx guardado de esa factura (None si aún no hay)."""
        rel = (c["invoice"] or {}).get("file")
        p = self.invoices / rel if rel else None
        return p if p and p.is_file() else None

    def render(self, d: dict, c: dict) -> bytes:
        cl = next((x for x in d["clients"] if x["id"] == c["client"]), {"name": c["who"]})
        return fill(self.template.read_bytes(), c["invoice"], cl, c["base"], c["iva"], c["irpf"])

    def write_invoice(self, d: dict, c: dict) -> None:
        """Guarda la factura rellena en facturas/<año>/<número> <cliente>.xlsx (sin plantilla, no hace nada)."""
        if not c["invoice"] or not self.template.is_file():
            return
        blob = self.render(d, c)
        cl = next((x for x in d["clients"] if x["id"] == c["client"]), {"name": c["who"]})
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", f"{c['invoice']['number']} {cl['name']}").strip()[:120]
        rel = f"{c['invoice']['date'][:4]}/{name}.xlsx"
        self.drop_invoice(c, keep=rel)
        write_private(self.invoices / rel, blob)
        c["invoice"]["file"] = rel

    def drop_invoice(self, c: dict, keep: str | None = None) -> None:
        rel = (c["invoice"] or {}).get("file")
        if rel and rel != keep:
            (self.invoices / rel).unlink(missing_ok=True)

    def write_missing(self, d: dict) -> int:
        """Las facturas que se hicieron sin plantilla (o cuyo archivo se borró): se guardan ahora."""
        n = 0
        for c in d["charges"]:
            if c["invoice"] and not self.invoice_file(d, c):
                self.write_invoice(d, c)
                n += 1
        return n

    def auto_invoice(self, d: dict, c: dict) -> bool:
        """Al quedar pagado del todo, la factura de un cargo con impuestos a un cliente se hace sola: siguiente número
        (o el que ya tuvo, si se borró el cobro por error),
        fecha del último cobro, una línea con el concepto (y el periodo) y cómo se pagó. Si ya la tiene, nada."""
        if c["invoice"] or not c["client"] or not c["taxes"] or not c["payments"] \
                or round(total(c) - paid(c), 2) > 0:
            return False
        last = max(c["payments"], key=lambda p: p["date"])
        concept = c["concept"] or "Servicios"
        if c.get("period"):
            a, b = (date.fromisoformat(x) for x in c["period"])
            concept += (f"\n(mes de {MONTHS[a.month - 1]} de {a.year})" if add_months(a, 1) - timedelta(days=1) == b
                        else f"\n(del {a:%d/%m/%Y} al {b:%d/%m/%Y})")
        year = last["date"][:4]
        held = next((a["number"] for a in d["annulled"] if a.get("reusable") and a["charge"] == c["id"]
                     and a["number"].startswith(f"{year}-")), None)
        self.invoice(d, c, {"number": held or self.next_number(d, int(year)), "date": last["date"],
                            "lines": [{"concept": concept, "qty": 1, "price": c["base"]}],
                            "pay_text": PAID_AS.get(last["method"], "Pagada")})
        c["invoice"]["auto"] = True  # si se borra el cobro, se deshace; si la cambias a mano, ya es tuya
        return True

    def next_number(self, d: dict, year: int) -> str:
        """El siguiente correlativo del año (2026-001, 2026-002…), contando las facturas apuntadas y las anuladas."""
        best, width = 0, 3
        used = [c["invoice"]["number"] for c in d["charges"] if c["invoice"]] + [a["number"] for a in d["annulled"]]
        for number in used:
            m = re.fullmatch(rf"{year}-(\d+)", number)
            if m:
                best, width = max(best, int(m.group(1))), max(width, len(m.group(1)))
        return f"{year}-{best + 1:0{width}d}"

    # ---------- lo que ve la interfaz ----------

    def due(self, c: dict) -> str:
        return c["due"] or (date.fromisoformat(c["date"]) + timedelta(days=self.due_days())).isoformat()

    def view(self, d: dict, today: date) -> dict:
        charges = []
        owed = late = 0.0
        month = today.isoformat()[:7]
        got_month = 0.0
        for c in d["charges"]:
            t, p = total(c), paid(c)
            left = round(t - p, 2)
            due = self.due(c)
            state = "paid" if left <= 0 else "late" if due < today.isoformat() else "pending"
            if state != "paid" and c["date"] <= today.isoformat():
                owed += left
                late += left if state == "late" else 0
            got_month += sum(x["amount"] for x in c["payments"] if x["date"][:7] == month)
            charges.append({**c, "total": t, "paid": p, "left": left, "state": state, "due_on": due})
        charges.sort(key=lambda c: (c["date"], c["concept"]))
        status, upcoming = self.status(d, charges, today)
        return {**d, "charges": charges, "status": status, "upcoming": upcoming, "next_number": self.next_number(d, today.year),
                "template": self.template.is_file(), "today": today.isoformat(),
                "settings": {"iva": self.iva(), "irpf": self.opt("irpf", 7.0), "due_days": self.due_days(),
                             "lead_days": int(self.opt("lead_days", 7)), "iban": text(self.opt("iban", ""), 60)},
                "summary": {"owed": round(owed, 2), "late": round(late, 2), "month": round(got_month, 2),
                            "pending": sum(1 for c in charges if c["state"] != "paid" and c["date"] <= today.isoformat()),
                            "late_n": sum(1 for c in charges if c["state"] == "late"),
                            "upcoming": sum(1 for c in charges if c["state"] != "paid" and c["date"] > today.isoformat()),
                            # cobrado y sin factura (lo que se cobra del todo la tiene sola: esto es lo de antes,
                            # o una que quitaste); lo que aún no te han pagado no cuenta, su factura llegará al cobrarlo
                            "uninvoiced": sum(1 for c in charges if c["client"] and c["taxes"] and not c["invoice"]
                                              and c["state"] == "paid")}}

    def status(self, d: dict, charges: list[dict], today: date) -> tuple[dict, list[dict]]:
        """Cómo va cada suscripción y lo que te van a deber.

        Por suscripción: la fecha del próximo pago y su estado: `late` si esa fecha ya ha llegado y no está pagada,
        `ok` si está pagado hasta entonces, `end` si está de baja y no debe nada.
        Lo próximo: la siguiente cuota de cada suscripción y los cargos con fecha futura, sin pagar."""
        t = today.isoformat()
        clients = {c["id"]: c for c in d["clients"]}
        by_sub: dict[str, list[dict]] = {}
        for c in charges:
            if c.get("sub"):
                by_sub.setdefault(c["sub"], []).append(c)
        status, upcoming = {}, []
        for s in d["subs"]:
            prod, plan = self.plan_of(d, s)
            cl = clients.get(s["client"])
            if not plan or not cl:
                continue
            cs = by_sub.get(s["id"], [])
            unpaid = [c for c in cs if c["left"] > 0]
            if unpaid:
                c = unpaid[0]
                st = {"state": "late" if c["date"] <= t else "ok", "next": c["date"], "charge": c["id"], "amount": c["left"]}
            else:
                spans = [c["period"] for c in cs if c.get("period")]
                a = next((a for a, b in self.periods(s, plan) if not covered(spans, a, b)), None)
                base = s["price"] if s.get("price") is not None else plan["price"]
                amount = total({"base": base, "iva": self.iva(), "irpf": cl.get("irpf", 0.0)})
                st = {"state": "ok" if a else "end", "next": a.isoformat() if a else None, "charge": None, "amount": amount}
            status[s["id"]] = st
            if st["state"] == "ok" and st["next"]:
                upcoming.append({"date": st["next"], "client": cl["id"], "who": cl["name"], "sub": s["id"],
                                 "charge": st["charge"], "concept": prod["name"], "amount": st["amount"]})
        for c in charges:
            if not c.get("sub") and c["left"] > 0 and c["date"] > t:
                upcoming.append({"date": c["date"], "client": c["client"],
                                 "who": clients.get(c["client"], {}).get("name", c["who"]), "sub": None,
                                 "charge": c["id"], "concept": c["concept"], "amount": c["left"]})
        upcoming.sort(key=lambda x: (x["date"], x["who"]))
        return status, upcoming


def plan_label(name: str) -> str:
    """«Básico» → «plan Básico»; «Plan Flexible» se queda como está (sin «plan Plan»)."""
    return name if name.lower().startswith("plan") else f"plan {name}"


ADJ = {"month": "mensual", "quarter": "trimestral", "year": "anual"}
