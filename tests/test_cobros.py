import asyncio
import io
import os
import re
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import load_config
from app.main import create_app
from app.modules.cobros import xlsx
from app.modules.cobros.api import Alerts
from app.modules.cobros.store import CobrosError, Store, add_months, money, total
from tests.test_modules import ReadyDeps

T = date(2026, 11, 4)


@pytest.fixture
def st(tmp_path):
    return Store(str(tmp_path), lambda: {"iva": "21", "irpf": "7", "due_days": 15, "lead_days": 7})


def base(st):
    d = st.load()
    p = st.upsert(d, "products", {"name": "ERP", "plans": [{"name": "Básico", "price": "12", "period": "month"},
                                                             {"name": "Anual", "price": 120, "period": "year"}]}, T)
    c = st.upsert(d, "clients", {"name": "Cliente SL", "nif": "b123", "irpf": 7}, T)
    return d, p, c


def test_money_and_months():
    assert money("1.234,50") == 1234.5 and money("12.5") == 12.5 and money(3) == 3
    with pytest.raises(CobrosError):
        money("mucho")
    with pytest.raises(CobrosError):
        money(-1)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert total({"base": 120, "iva": 21, "irpf": 7}) == 136.8


def test_monthly_sub_with_free_months(st):
    d, p, c = base(st)
    st.upsert(d, "subs", {"client": c["id"], "product": p["id"], "plan": p["plans"][0]["id"],
                          "start": "2026-09-01", "free_until": "2026-11-01", "price": "15"}, T)
    new = st.sync(d, T)
    # sep y oct gratis; nov ya toca; dic aún no (faltan más de 7 días)
    assert [x["period"] for x in new] == [["2026-11-01", "2026-11-30"]]
    assert new[0]["base"] == 15 and new[0]["concept"] == "Suscripción mensual a ERP, plan Básico"
    assert st.sync(d, T) == []  # no se repite
    assert [x["date"] for x in st.sync(d, date(2026, 11, 25))] == ["2026-12-01"]


def test_deleted_charge_does_not_come_back(st):
    d, p, c = base(st)
    s = st.upsert(d, "subs", {"client": c["id"], "product": p["id"], "plan": p["plans"][1]["id"], "start": "2026-11-04"}, T)
    [ch] = st.sync(d, T)
    assert ch["period"] == ["2026-11-04", "2027-11-03"] and ch["irpf"] == 7
    st.delete(d, "charges", ch["id"])
    assert st.sync(d, T) == [] and s["skip"] == ["2026-11-04"]


def test_payments_invoice_and_state(st):
    d, p, c = base(st)
    ch = st.upsert(d, "charges", {"client": c["id"], "concept": "Web", "base": "1000"}, T)
    assert ch["iva"] == 21 and ch["irpf"] == 7
    st.pay(ch, {"amount": 570, "method": "bizum"}, T)
    v = st.view(d, T)
    [x] = v["charges"]
    assert x["total"] == 1140 and x["left"] == 570 and x["state"] == "pending" and v["summary"]["owed"] == 570
    assert st.view(d, date(2026, 12, 1))["charges"][0]["state"] == "late"
    st.pay(ch, {"amount": 570}, T)
    assert st.view(d, T)["charges"][0]["state"] == "paid"
    with pytest.raises(CobrosError):
        st.invoice(d, ch, {"number": "2026-001", "date": "2026-11-04", "lines": []})
    st.invoice(d, ch, {"number": "2026-001", "date": "2026-11-04", "lines": [{"concept": "Web", "qty": 2, "price": 500}]})
    assert st.next_number(d, 2026) == "2026-002" and st.next_number(d, 2027) == "2027-001"
    other = st.upsert(d, "charges", {"client": c["id"], "concept": "Otra", "base": 1}, T)
    with pytest.raises(CobrosError, match="Ya hay otra"):
        st.invoice(d, other, {"number": "2026-001", "date": "2026-11-04", "lines": [{"concept": "x", "price": 1}]})
    with pytest.raises(CobrosError, match="factura"):
        st.delete(d, "charges", ch["id"])
    with pytest.raises(CobrosError, match="facturas"):
        st.delete(d, "clients", c["id"])


def test_loose_debt_has_no_taxes(st):
    d = st.load()
    ch = st.upsert(d, "charges", {"who": "Pepe", "concept": "Entradas", "base": "20"}, T)
    assert (ch["iva"], ch["irpf"], total(ch)) == (0, 0, 20)
    with pytest.raises(CobrosError):
        st.upsert(d, "charges", {"concept": "x", "base": 1}, T)
    assert st.upsert(d, "charges", {"who": "Ana", "base": 5}, T)["concept"] == ""  # sin concepto vale
    d, _, c = base(st)
    with pytest.raises(CobrosError, match="concepto"):
        st.upsert(d, "charges", {"client": c["id"], "base": 5}, T)


def test_invoice_made_when_fully_paid(st):
    d, p, c = base(st)
    s = st.upsert(d, "subs", {"client": c["id"], "product": p["id"], "plan": p["plans"][1]["id"], "start": "2026-11-04"}, T)
    st.upsert(d, "subs", {**s, "id": None, "plan": p["plans"][0]["id"]}, T)
    yearly, monthly = sorted(st.sync(d, T), key=lambda x: x["base"], reverse=True)
    st.pay(yearly, {"amount": 60}, T)
    assert not st.auto_invoice(d, yearly)                      # a medias, todavía no
    st.pay(yearly, {"amount": total(yearly) - 60, "method": "bizum", "date": "2026-11-05"}, T)
    assert st.auto_invoice(d, yearly) and not st.auto_invoice(d, yearly)
    inv = yearly["invoice"]
    assert (inv["number"], inv["date"], inv["pay_text"]) == ("2026-001", "2026-11-05", "Pagada por Bizum")
    assert inv["lines"] == [{"concept": "Suscripción anual a ERP, plan Anual\n(del 04/11/2026 al 03/11/2027)", "qty": 1, "price": 120}]
    st.pay(monthly, {"amount": total(monthly)}, T)
    assert st.auto_invoice(d, monthly) and monthly["invoice"]["number"] == "2026-002"
    assert monthly["invoice"]["lines"][0]["concept"].endswith("(mes de noviembre de 2026)")
    loose = st.upsert(d, "charges", {"who": "Pepe", "base": 10}, T)
    st.pay(loose, {"amount": 10}, T)
    assert not st.auto_invoice(d, loose)                       # sin cliente, sin factura


def test_sub_status_and_upcoming(st):
    d, p, c = base(st)
    yearly = p["plans"][1]["id"]
    late = st.upsert(d, "subs", {"client": c["id"], "product": p["id"], "plan": yearly, "start": "2026-10-10"}, T)
    two = st.upsert(d, "clients", {"name": "Bea", "irpf": 0}, T)
    ok = st.upsert(d, "subs", {"client": two["id"], "product": p["id"], "plan": yearly, "start": "2025-11-01"}, T)
    free = st.upsert(d, "subs", {"client": two["id"], "product": p["id"], "plan": yearly, "start": "2026-11-01",
                                 "free_until": "2027-11-01"}, T)
    st.sync(d, T)
    for ch in d["charges"]:
        if ch["sub"] == ok["id"]:
            st.pay(ch, {"amount": total(ch)}, T)
    st.upsert(d, "charges", {"who": "Dani", "concept": "Cena", "base": 20, "date": "2026-12-20"}, T)
    v = st.view(d, T)
    s = v["status"]
    assert s[late["id"]]["state"] == "late" and s[late["id"]]["next"] == "2026-10-10" and s[late["id"]]["amount"] == 136.8
    assert s[ok["id"]] == {"state": "ok", "next": "2027-11-01", "charge": None, "amount": 145.2}  # 120 + IVA, sin IRPF
    assert s[free["id"]]["next"] == "2027-11-01" and s[free["id"]]["state"] == "ok"
    assert [(u["date"], u["who"], u["concept"]) for u in v["upcoming"]] == [
        ("2026-12-20", "Dani", "Cena"), ("2027-11-01", "Bea", "ERP"), ("2027-11-01", "Bea", "ERP")]
    st.upsert(d, "subs", {**ok, "end": "2026-12-01"}, T)
    assert st.view(d, T)["status"][ok["id"]] == {"state": "end", "next": None, "charge": None, "amount": 145.2}


def test_plan_in_use_cannot_go(st):
    d, p, c = base(st)
    st.upsert(d, "subs", {"client": c["id"], "product": p["id"], "plan": p["plans"][0]["id"], "start": "2026-11-01"}, T)
    with pytest.raises(CobrosError):
        st.upsert(d, "products", {"id": p["id"], "name": "ERP", "plans": [p["plans"][1]]}, T)
    with pytest.raises(CobrosError):
        st.delete(d, "products", p["id"])


def test_saved_file_is_private(st):
    st.save(st.load())
    assert os.stat(st.path).st_mode & 0o777 == 0o600


# ---------- plantilla ----------

def cell(ref, inner="", s="1", t=None):
    return f'<c r="{ref}" s="{s}"{f" t={chr(34)}{t}{chr(34)}" if t else ""}>{inner}</c>' if inner else f'<c r="{ref}" s="{s}"/>'


def template() -> bytes:
    """Una plantilla mínima con las celdas que se rellenan (la de verdad lleva además los datos del emisor)."""
    refs = [r for refs in xlsx.NEEDED.values() for r in refs]
    f = "".join(cell(r, "<f>SUM(D18:D21)</f><v>0</v>" if r[0] == "D" and r != "D1" and r != "D2" else "") for r in xlsx.NEEDED["Factura"])
    i = "".join(cell(r) for r in xlsx.NEEDED["Instrucciones"])
    assert refs
    ws = '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">{}</row></sheetData></worksheet>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns:r="r"><sheets><sheet name="Factura" sheetId="1" r:id="rId3"/>'
                                      '<sheet name="Instrucciones" sheetId="2" r:id="rId4"/></sheets><calcPr iterate="false"/></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId3" Type="ws" Target="worksheets/sheet1.xml"/>'
                                                 '<Relationship Id="rId4" Type="ws" Target="worksheets/sheet2.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", ws.format(f))
        z.writestr("xl/worksheets/sheet2.xml", ws.format(i))
        z.writestr("docProps/app.xml", "<x/>")
    return b.getvalue()


def test_fill_template():
    inv = {"number": "2026-002", "date": "2026-11-04", "pay_text": "Pagada en efectivo",
           "lines": [{"concept": "Suscripción anual a ERP\n(del 04/11/2026 al 03/11/2027)", "qty": 1, "price": 120}]}
    out = xlsx.fill(template(), inv, {"name": "Ana & Cía", "nif": "B1", "address": "C/ Uno", "city": "Madrid"}, 120, 21, 7)
    z = zipfile.ZipFile(io.BytesIO(out))
    s1, s2 = z.read("xl/worksheets/sheet1.xml").decode(), z.read("xl/worksheets/sheet2.xml").decode()
    assert '<c r="D1" s="1" t="inlineStr"><is><t xml:space="preserve">2026-002</t></is></c>' in s1
    assert '<c r="D2" s="1" t="n"><v>46330</v></c>' in s1
    assert "Ana &amp; Cía" in s1 and "NIF B1" in s1 and "Pagada en efectivo" in s1
    assert '<c r="D26" s="1" t="n"><f>SUM(D18:D21)</f><v>136.8</v></c>' in s1  # fórmula intacta, resultado nuevo
    assert '<c r="D25" s="1" t="n"><f>SUM(D18:D21)</f><v>-8.4</v></c>' in s1
    assert '<c r="B19" s="1"/>' in s1 and '<c r="A19" s="1"/>' in s1
    assert "<v>0.07</v>" in s2 and "<v>0.21</v>" in s2
    assert 'fullCalcOnLoad="1"' in z.read("xl/workbook.xml").decode()
    assert z.read("docProps/app.xml") == b"<x/>"


def test_template_check():
    xlsx.check(template())
    with pytest.raises(xlsx.TemplateError):
        xlsx.check(b"no soy un zip")
    broken = re.sub(rb'<c r="A30"[^>]*/>', b"", zipfile.ZipFile(io.BytesIO(template())).read("xl/worksheets/sheet1.xml"))
    b = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(template())) as src, zipfile.ZipFile(b, "w") as z:
        for it in src.infolist():
            z.writestr(it, broken if it.filename.endswith("sheet1.xml") else src.read(it.filename))
    with pytest.raises(xlsx.TemplateError, match="A30"):
        xlsx.check(b.getvalue())


# ---------- API y avisos ----------

@pytest.fixture
def api(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text("modules: {cobros: {enabled: true}}")
    cfg = load_config(str(p), {"PANEL_PIN_HASH": auth.hash_pin("1234"), "PANEL_SECRET": "s", "PANEL_DATA": str(tmp_path / "data")})
    c = TestClient(create_app(cfg, deps=ReadyDeps(cfg.data_dir)))
    assert c.post("/api/login", json={"pin": "1234"}).status_code == 200
    return c


def test_api(api, tmp_path):
    assert api.get("/api/cobros").json()["summary"]["owed"] == 0
    r = api.post("/api/cobros/clients", json={"name": "Ana"}).json()
    cid = r["saved"]
    assert api.post("/api/cobros/clients", json={"name": ""}).status_code == 400
    r = api.post("/api/cobros/charges", json={"client": cid, "concept": "Web", "base": 100, "taxes": False}).json()
    ch = r["saved"]
    assert r["summary"]["owed"] == 100
    assert api.post(f"/api/cobros/charges/{ch}/pay", json={"amount": 100}).json()["summary"]["owed"] == 0  # sin IVA: sin factura
    taxed = api.post("/api/cobros/charges", json={"client": cid, "concept": "Soporte", "base": 10}).json()["saved"]
    r = api.post(f"/api/cobros/charges/{taxed}/pay", json={"amount": 11.4}).json()  # 10 + IVA − IRPF
    assert next(x for x in r["charges"] if x["id"] == taxed)["invoice"]["number"] == "2026-001"  # pagado: factura hecha
    assert api.get(f"/api/cobros/charges/{ch}/factura.xlsx").status_code == 404
    assert api.delete(f"/api/cobros/charges/{taxed}/invoice").status_code == 200
    api.post(f"/api/cobros/charges/{ch}/invoice", json={"number": "2026-001", "date": "2026-11-04", "lines": [{"concept": "Web", "price": 100}]})
    assert api.get(f"/api/cobros/charges/{ch}/factura.xlsx").status_code == 404  # sin plantilla
    assert api.put("/api/cobros/plantilla.xlsx", content=b"basura").status_code == 400
    assert api.put("/api/cobros/plantilla.xlsx", content=template()).status_code == 200
    saved = tmp_path / "data/cobros/facturas/2026/2026-001 Ana.xlsx"  # al subir la plantilla se guardan las que faltaban
    assert saved.is_file() and oct(saved.stat().st_mode & 0o777) == "0o600"
    r = api.get(f"/api/cobros/charges/{ch}/factura.xlsx")
    assert r.status_code == 200 and "2026-001%20Ana.xlsx" in r.headers["content-disposition"] and r.content == saved.read_bytes()
    # cambiar el número la mueve; quitarla la borra
    api.post(f"/api/cobros/charges/{ch}/invoice", json={"number": "2026-007", "date": "2026-11-04", "lines": [{"concept": "Web", "price": 100}]})
    assert not saved.exists() and (saved.parent / "2026-007 Ana.xlsx").is_file()
    assert api.delete(f"/api/cobros/charges/{ch}/invoice").status_code == 200
    assert list(saved.parent.iterdir()) == []
    assert api.get("/api/cobros").json()["folder"].endswith("cobros/facturas")
    assert api.post("/api/cobros/nada", json={}).status_code == 400
    assert api.get("/modules/cobros/index.js").status_code == 200


def test_alerts_once_a_day(st):
    d, p, c = base(st)
    ch = st.upsert(d, "charges", {"client": c["id"], "concept": "Web", "base": 100, "date": "2026-10-01"}, T)
    st.save(d)

    class Ctx:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Madrid")

    a = Alerts(st, Ctx())
    nine = lambda dd, h=9: __import__("datetime").datetime(dd.year, dd.month, dd.day, h, tzinfo=Ctx.tz).timestamp()  # noqa: E731
    assert asyncio.run(a.tick(0, nine(T, 8))) == []                  # antes de las 9, nada
    [(msg, url)] = asyncio.run(a.tick(0, nine(T)))
    assert "toca cobrar Cliente SL · Web" in msg and url == "/#cobros"
    assert asyncio.run(a.tick(0, nine(T))) == []                     # una vez al día
    [(msg, _)] = asyncio.run(a.tick(0, nine(date(2026, 11, 5))))
    assert "sin pagar todavía" in msg
    assert asyncio.run(a.tick(0, nine(date(2026, 11, 6)))) == []     # cada cosa, una vez
    assert ch["id"] in {x["id"] for x in st.load()["charges"]}
