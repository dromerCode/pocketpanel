import logging
from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from ... import auth
from ...core import json_body
from .store import CobrosError, Store, paid, total
from .xlsx import TemplateError, check, fill

log = logging.getLogger("pocketpanel.cobros")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_TEMPLATE = 2 * 1024 * 1024


def _attachment(name: str) -> str:
    plain = name.encode("ascii", "replace").decode().replace('"', "_").replace("?", "_")
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}"


def _eur(n: float) -> str:
    return f"{n:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


class Alerts:
    """Cada día a las 9: aviso de las cuotas que ya tocan y de lo que lleva tiempo sin pagar (una vez cada cosa)."""

    def __init__(self, store: Store, ctx):
        self.store, self.ctx, self.last = store, ctx, None

    def who(self, d, c):
        return next((x["name"] for x in d["clients"] if x["id"] == c["client"]), c["who"])

    async def tick(self, n, now):
        if not self.store.settings().get("alerts", True):
            return []
        local = datetime.fromtimestamp(now, self.ctx.tz)
        today = local.date()
        if local.hour < 9 or self.last == today:
            return []
        self.last = today
        d = self.store.load()
        self.store.sync(d, today)
        new, late = [], []
        for c in d["charges"]:
            if round(total(c) - paid(c), 2) <= 0:
                continue
            if "new" not in c["alerted"]:
                c["alerted"].append("new")
                new.append(c)
            elif "late" not in c["alerted"] and self.store.due(c) < today.isoformat():
                c["alerted"].append("late")
                late.append(c)
        self.store.save(d)
        notes = []
        if new:
            notes.append((f"Cobros: toca cobrar {self.list(d, new)}", "/#cobros"))
        if late:
            notes.append((f"Cobros: sin pagar todavía {self.list(d, late)}", "/#cobros"))
        return notes

    def list(self, d, cs):
        if len(cs) == 1:
            c = cs[0]
            return f"{self.who(d, c)} · {c['concept']} ({_eur(total(c) - paid(c))})"
        return f"{len(cs)} cosas ({_eur(sum(total(c) - paid(c) for c in cs))}): " + ", ".join(self.who(d, c) for c in cs)


def setup(ctx) -> APIRouter:
    store = Store(ctx.cfg.data_dir, lambda: ctx.cfg.mod("cobros"))
    ctx.hooks.append(Alerts(store, ctx))
    r = APIRouter(prefix="/api/cobros", dependencies=[Depends(auth.require_auth)])

    # la carpeta de facturas vista desde el host (para abrirla en Archivos)
    folder = f"{ctx.cfg.host_dir.rstrip('/')}/data/cobros/facturas" if ctx.cfg.host_dir else str(store.invoices)

    def today() -> date:
        return datetime.now(ctx.tz).date()

    def view(d):
        return {**store.view(d, today()), "folder": folder}

    def change(fn):
        """Carga, cambia, guarda y devuelve todo (la interfaz se repinta con eso)."""
        d = store.load()
        try:
            out = fn(d)
        except (CobrosError, TemplateError) as e:
            raise HTTPException(400, str(e))
        store.sync(d, today())
        store.save(d)
        return {**view(d), "saved": out["id"] if isinstance(out, dict) and "id" in out else None}

    @r.get("")
    async def everything():
        try:
            d = store.load()
        except CobrosError as e:
            raise HTTPException(500, str(e))
        changed = bool(store.sync(d, today()))
        if store.template.is_file():
            try:  # las facturas que aún no estén en la carpeta (hechas antes de tener plantilla, o borradas a mano)
                changed |= bool(store.write_missing(d))
            except TemplateError as e:
                log.warning("cobros: no se pudieron guardar facturas: %s", e)
        if changed:
            store.save(d)
        return view(d)

    @r.post("/{kind}")
    async def upsert(kind: str, request: Request):
        b = await json_body(request)
        return change(lambda d: store.upsert(d, kind, b, today()))

    @r.delete("/{kind}/{id_}")
    async def delete(kind: str, id_: str):
        return change(lambda d: store.delete(d, kind, id_))

    @r.post("/charges/{id_}/pay")
    async def pay(id_: str, request: Request):
        b = await json_body(request)

        def collect(d):
            c = store.charge(d, id_)
            store.pay(c, b, today())
            if store.auto_invoice(d, c):  # pagado del todo: su factura, hecha y guardada en la carpeta
                try:
                    store.write_invoice(d, c)
                except TemplateError as e:  # el cobro se apunta igual; el archivo se guarda cuando se arregle
                    log.warning("cobros: factura %s sin archivo: %s", c["invoice"]["number"], e)
        return change(collect)

    @r.delete("/charges/{id_}/pay/{i}")
    async def unpay(id_: str, i: int):
        return change(lambda d: store.unpay(store.charge(d, id_), i))

    @r.post("/charges/{id_}/invoice")
    async def invoice(id_: str, request: Request):
        b = await json_body(request)

        def make(d):
            c = store.charge(d, id_)
            store.invoice(d, c, b)
            store.write_invoice(d, c)  # también la guarda en la carpeta de facturas
        return change(make)

    @r.delete("/charges/{id_}/invoice")
    async def uninvoice(id_: str):
        def drop(d):
            c = store.charge(d, id_)
            store.drop_invoice(c)
            c["invoice"] = None
        return change(drop)

    @r.get("/charges/{id_}/factura.xlsx")
    async def download(id_: str):
        d = store.load()
        try:
            c = store.charge(d, id_)
        except CobrosError as e:
            raise HTTPException(404, str(e))
        if not c["invoice"]:
            raise HTTPException(404, "Esto aún no tiene factura")
        saved = store.invoice_file(d, c)
        if saved:  # la que se guardó al hacerla, tal cual
            blob, name = saved.read_bytes(), saved.name
        elif not store.template.is_file():
            raise HTTPException(404, "Sube antes tu plantilla (.xlsx)")
        else:
            try:
                store.write_invoice(d, c)
                store.save(d)
                blob, name = store.invoice_file(d, c).read_bytes(), store.invoice_file(d, c).name
            except TemplateError as e:
                raise HTTPException(400, str(e))
        return Response(blob, media_type=XLSX, headers={"Content-Disposition": _attachment(name),
                                                        "Cache-Control": "no-store"})

    @r.get("/plantilla.xlsx")
    async def template():
        if not store.template.is_file():
            raise HTTPException(404, "Todavía no has subido la plantilla")
        return Response(store.template.read_bytes(), media_type=XLSX,
                        headers={"Content-Disposition": _attachment("plantilla-factura.xlsx"), "Cache-Control": "no-store"})

    @r.put("/plantilla.xlsx")
    async def upload(request: Request):
        blob = await request.body()
        if len(blob) > MAX_TEMPLATE:
            raise HTTPException(413, "La plantilla no puede pasar de 2 MB")
        try:
            check(blob)
        except TemplateError as e:
            raise HTTPException(400, str(e))
        store.save_template(blob)
        d = store.load()
        try:
            if store.write_missing(d):  # las facturas hechas antes de tener plantilla
                store.save(d)
        except TemplateError as e:
            log.warning("cobros: no se pudieron guardar las facturas pendientes: %s", e)
        return {"ok": True}

    return r
