"""El JS del widget, en node y con un DOM mínimo: tailscale.js de verdad, api.js y widgets.js de mentira."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

API = """
export const api = (...a) => globalThis.apiCall(...a);
export const el = (tag, attrs, ...children) => ({ tag, attrs, children });
export const fmtAgo = () => "hace poco";
export const toast = (msg) => globalThis.toasts.push(msg);
"""
WIDGETS = "export const layoutReady = globalThis.layout;\n"

TESTS = r"""
import assert from "node:assert/strict";
import { test, beforeEach } from "node:test";

globalThis.layout = new Promise((r) => { globalThis.layoutLoaded = r; });
const { loadTailscale, initTailscale } = await import("./tailscale.js");

let w, badge, list, calls;
const running = { state: "Running", online: 1, devices: [{ name: "a", online: true, os: "linux" }] };
const answer = (t) => { globalThis.apiCall = async () => { calls++; return t; }; };

beforeEach(() => {
  calls = 0;
  globalThis.toasts = [];
  const listeners = {};
  w = { hidden: false, dataset: { absent: "" }, addEventListener: (n, f) => { listeners[n] = f; }, fire: (n) => listeners[n]() };
  badge = { textContent: "", className: "badge" };
  list = { replaceChildren(...c) { this.items = c; } };
  globalThis.document = {
    querySelector: () => w,
    getElementById: (id) => ({ "ts-badge": badge, "ts-list": list })[id],
  };
  answer(running);
});

test("hasta que llega la organización guardada no se pide nada", async () => {
  const pending = loadTailscale();
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(calls, 0);
  w.hidden = true;  // lo guardado decía que estaba oculto
  layoutLoaded();
  await pending;
  assert.equal(calls, 0);
});

test("con Tailscale el widget se enseña", async () => {
  await loadTailscale();
  assert.equal(w.dataset.absent, undefined);
  assert.equal(badge.className, "badge ok");
});

test("sin Tailscale se aparta, pero sigue ahí y vuelve si aparece", async () => {
  answer({ state: "absent", devices: [] });
  await loadTailscale();
  assert.equal(w.dataset.absent, "");
  assert.equal(w.hidden, false);  // no toca lo que guarda la organización
  answer(running);
  await loadTailscale();
  assert.equal(w.dataset.absent, undefined);
});

test("dos cargas a la vez sin Tailscale no revientan", async () => {
  answer({ state: "absent", devices: [] });
  await Promise.all([loadTailscale(), loadTailscale()]);
  assert.equal(w.dataset.absent, "");
});

test("un error se enseña en ámbar, también si antes estaba bien", async () => {
  await loadTailscale();
  globalThis.apiCall = async () => { throw new Error("sin conexión"); };
  await loadTailscale();
  assert.equal(badge.textContent, "Sin datos");
  assert.equal(badge.className, "badge warn");
  assert.equal(w.dataset.absent, undefined);
});

test("un error en la primera carga también se ve", async () => {
  globalThis.apiCall = async () => { throw new Error("sin conexión"); };
  await loadTailscale();
  assert.equal(w.dataset.absent, undefined);
});

test("sacarlo de ocultos en un servidor sin Tailscale lo dice", async () => {
  answer({ state: "absent", devices: [] });
  initTailscale();
  await w.fire("wshow");
  assert.equal(toasts.length, 1);
});
"""


@pytest.mark.skipif(not shutil.which("node"), reason="sin node")
def test_widget(tmp_path):
    shutil.copy(ROOT / "web" / "js" / "tailscale.js", tmp_path)
    (tmp_path / "api.js").write_text(API)
    (tmp_path / "widgets.js").write_text(WIDGETS)
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "t.mjs").write_text(TESTS)
    r = subprocess.run(["node", "--test", "--test-reporter=spec", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr


def test_widget_starts_out_of_the_way():
    # Sin parpadeo en un servidor sin Tailscale: no sale hasta saber que lo hay
    html = (ROOT / "web" / "index.html").read_text()
    assert 'data-w="tailscale" data-absent' in html
    assert ".w[data-absent]" in (ROOT / "web" / "app.css").read_text()
