// Los widgets de Estado: orden, ancho y ocultos, a gusto del usuario y guardados en el servidor (/api/layout).
//
// Cada widget es un .w en #st-grid con data-w (id), data-size (ancho por defecto: columnas de 4), data-rank
// (dónde sale por defecto) y data-title. Los del núcleo están en index.html; las tarjetas de los módulos las pone
// registry.js. Un widget que no está en lo guardado (p. ej. el de un módulo recién activado) sale en su sitio por
// defecto.
import { api, el, toast } from "./api.js";

const COLS = 4;  // la rejilla: 1 = un cuarto del ancho, 4 = todo
const $ = (id) => document.getElementById(id);
const grid = () => $("st-grid");
const widgets = () => [...grid().children].filter((w) => w.classList.contains("w"));
let defaults = null;  // id → { size, rank }, como vienen de index.html / registry.js
let saveTimer = null;

function setSize(w, size) {
  w.dataset.cur = size;
  w.style.setProperty("--span", size);
}

/** Pone el orden, los anchos y los ocultos de `items` ([{id, size, hidden}]); lo que no está, en su sitio. */
function apply(items) {
  const byId = new Map(items.map((it, i) => [it.id, { ...it, i }]));
  const all = widgets();
  for (const w of all) {
    const it = byId.get(w.dataset.w);
    setSize(w, it?.size ?? defaults[w.dataset.w].size);
    w.hidden = !!it?.hidden;
  }
  // Los guardados en su orden; cada uno de los nuevos, justo antes del primer guardado que iba detrás de él
  const known = all.filter((w) => byId.has(w.dataset.w)).sort((a, b) => byId.get(a.dataset.w).i - byId.get(b.dataset.w).i);
  const order = [...known];
  const fresh = all.filter((x) => !byId.has(x.dataset.w)).sort((a, b) => defaults[a.dataset.w].rank - defaults[b.dataset.w].rank);
  for (const w of fresh) {
    const rank = defaults[w.dataset.w].rank;
    const at = order.findIndex((x) => known.includes(x) && defaults[x.dataset.w].rank > rank);
    order.splice(at < 0 ? order.length : at, 0, w);
  }
  grid().append(...order);
  renderTray();
}

const current = () => widgets().map((w) => ({ id: w.dataset.w, size: Number(w.dataset.cur), hidden: w.hidden }));

function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    try {
      await api("/api/layout", { method: "PUT", body: { widgets: current() } });
    } catch (e) {
      toast(`No se pudo guardar la organización: ${e.message}`, true);
    }
  }, 400);
}

function renderTray() {
  const off = widgets().filter((w) => w.hidden);
  const tray = $("st-hidden");
  tray.hidden = !grid().classList.contains("editing") || !off.length;
  tray.replaceChildren(el("span", { class: "muted small" }, "Ocultos:"), ...off.map((w) =>
    el("button", { class: "btn btn-sm", type: "button", onclick: () => { w.hidden = false; renderTray(); save(); } },
      `+ ${w.dataset.title}`)));
}

function resize(w, size) {
  if (size === Number(w.dataset.cur)) return;
  setSize(w, size);
  w.querySelector(":scope > .wtools").replaceWith(tools(w));
  save();
}

/** Arrastrar con el ⠿ (ratón o dedo): el widget se va colocando donde pasa el puntero. Se escucha en window: al
 * mover el widget en el DOM el ⠿ pierde la captura del puntero. */
function drag(w, e) {
  e.preventDefault();
  w.classList.add("dragging");
  const scroller = w.closest(".scroll");
  let y = e.clientY;
  const auto = setInterval(() => {  // acercarse al borde desplaza la página
    const r = scroller.getBoundingClientRect();
    if (y < r.top + 60) scroller.scrollBy(0, -12);
    else if (y > r.bottom - 60) scroller.scrollBy(0, 12);
  }, 16);
  const move = (ev) => {
    if (ev.pointerId !== e.pointerId) return;
    y = ev.clientY;
    const t = document.elementFromPoint(ev.clientX, ev.clientY)?.closest("#st-grid > .w");
    if (!t || t === w || t.hidden) return;
    const all = widgets();
    t[all.indexOf(w) < all.indexOf(t) ? "after" : "before"](w);
  };
  const end = (ev) => {
    if (ev.pointerId !== e.pointerId) return;
    clearInterval(auto);
    w.classList.remove("dragging");
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", end);
    window.removeEventListener("pointercancel", end);
    save();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", end);
  window.addEventListener("pointercancel", end);
}

/** Cuatro casillas, una por columna: las rellenas son lo que ocupa; tocar la tercera lo deja en 3 de 4. */
function widthPicker(w) {
  const cur = Number(w.dataset.cur);
  return el("span", { class: "wwidth", role: "group", "aria-label": `Ancho de ${w.dataset.title}` },
    ...Array.from({ length: COLS }, (_, i) => el("button", {
      type: "button", class: i < cur ? "on" : "", title: `${i + 1} de ${COLS} columnas`,
      "aria-pressed": String(i + 1 === cur), onclick: () => resize(w, i + 1),
    })));
}

function tools(w) {
  const b = (label, title, fn) => el("button", { type: "button", class: "wtool", title, "aria-label": `${title}: ${w.dataset.title}`, onclick: fn }, label);
  const handle = el("button", { type: "button", class: "wtool whandle", title: "Mover", "aria-label": `Mover ${w.dataset.title}` }, "⠿");
  handle.addEventListener("pointerdown", (e) => drag(w, e));
  return el("div", { class: "wtools" }, handle,
    el("span", { class: "wname" }, w.dataset.title),
    widthPicker(w),
    b("✕", "Ocultar", () => { w.hidden = true; renderTray(); save(); }));
}

function edit(on) {
  grid().classList.toggle("editing", on);
  $("st-editbar").hidden = !on;
  for (const w of widgets()) {
    w.querySelector(":scope > .wtools")?.remove();
    if (on) w.prepend(tools(w));
    // que un clic en una tarjeta-enlace no navegue mientras se organiza
    for (const c of w.children) if (!c.classList.contains("wtools")) c.inert = on;
  }
  renderTray();
}

export async function initWidgets() {
  defaults = Object.fromEntries(widgets().map((w) => [w.dataset.w, { size: Number(w.dataset.size), rank: Number(w.dataset.rank) }]));
  apply([]);
  $("st-edit").onclick = () => edit(!grid().classList.contains("editing"));
  $("st-done").onclick = () => edit(false);
  $("st-reset").onclick = () => {
    if (!confirm("¿Volver a la organización por defecto?")) return;
    apply([]);
    edit(true);
    save();
  };
  try {
    apply((await api("/api/layout")).widgets);
  } catch (e) {
    if (e.message !== "no autenticado") toast(`Organización: ${e.message}`, true);
  }
}

export const leaveWidgets = () => edit(false);
