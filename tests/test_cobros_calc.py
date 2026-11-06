"""Las cuentas y los textos del JS de Cobros, en node: tienen que coincidir con los del servidor."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

TESTS = r"""
import assert from "node:assert/strict";
import { test } from "node:test";
import { heldNumber, monthText, num, pct, round2, totalOf } from "./calc.js";

test("heldNumber: el número reservado de ese cargo, solo si es de este año (como auto_invoice)", () => {
  const annulled = [
    { number: "2026-003", charge: "a", reusable: false },
    { number: "2025-009", charge: "b", reusable: true },
    { number: "2026-004", charge: "c", reusable: true },
  ];
  assert.equal(heldNumber(annulled, "c", "2026-11-06"), "2026-004");
  assert.equal(heldNumber(annulled, "a", "2026-11-06"), undefined);  // anulado de verdad: no se vuelve a ofrecer
  assert.equal(heldNumber(annulled, "b", "2026-11-06"), undefined);  // de otro año: no iría en orden
});

test("num entiende los miles a la española", () => {
  assert.equal(num("1.234"), 1234);
  assert.equal(num("12.000"), 12000);
  assert.equal(num("1.234.567"), 1234567);
  assert.equal(num("1.234,50"), 1234.5);
  assert.equal(num("12,5"), 12.5);
  assert.equal(num("12.5"), 12.5);
  assert.equal(num("12.50"), 12.5);
  assert.equal(num("0.125"), 0.125);
  assert.equal(num(" 1.234 € "), 1234);
});

test("redondea los medios hacia arriba, sin ruido binario", () => {
  assert.equal(pct(12.5, 21), 2.63);
  assert.equal(pct(4.1, 15), 0.62);
  assert.equal(pct(1.15, 21), 0.24);
  assert.equal(pct(-12.5, 21), -2.63);
  assert.equal(round2(0.5 * 0.25), 0.13);
});

test("el total coincide con el del servidor", () => {
  assert.equal(totalOf(12.5, 21, 0), 15.13);
  assert.equal(totalOf(4.1, 15, 0), 4.72);
  assert.equal(totalOf(12.5, 0, 21), 9.87);
  assert.equal(totalOf(120, 21, 7), 136.8);
});

test("el mes de la factura lleva un solo «de»", () => {
  assert.equal(monthText("2026-11-01"), "noviembre de 2026");
});
"""


@pytest.mark.skipif(not shutil.which("node"), reason="sin node")
def test_calc(tmp_path):
    shutil.copy(ROOT / "app" / "modules" / "cobros" / "web" / "calc.js", tmp_path)
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "t.mjs").write_text(TESTS)
    r = subprocess.run(["node", "--test", "--test-reporter=spec", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
