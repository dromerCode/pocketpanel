import { api, el, fmtBytes, serviceIcon, toast, wsUrl } from "./api.js";
import { closeSheet as closeUSheet, initSheet } from "./ui.js";

let items = [];
let filter = "all";
let timer = null;
let open = null;      // servicio de la ficha abierta
let logWs = null;
let paused = false;
let pending = "";
const $ = (id) => document.getElementById(id);

/* ---------- Para los módulos (Actualizaciones, Backups…) ---------- */

const filters = {};           // id → { match(s), empty() }
const sheetButtons = [];      // { node, fill(s) }
const showHooks = [];

/** Un filtro más junto a Todos/Caídos: `match(servicio)` decide si sale; `empty()`, el texto si no sale ninguno. */
export function addFilter(id, label, match, empty) {
  filters[id] = { match, empty };
  const b = el("button", { class: "seg-btn", "data-filter": id }, label);
  b.onclick = () => setFilter(id);
  document.querySelector("#view-services .topbar .seg").append(b);
}

/** Un botón (o lo que sea) en la cabecera de Servicios. */
export const addHeader = (node) => document.querySelector("#view-services .topbar").append(node);
/** Una línea bajo el buscador (p. ej. "3 actualizaciones disponibles"). */
export const addInfo = (node) => document.querySelector("#view-services .search-wrap").append(node);
/** Un botón en la ficha de un servicio; `fill(servicio)` lo ajusta cada vez que se pinta la ficha.
 * `first`: junto a «Abrir» en vez de al final. */
export function addSheetButton(node, fill, first = false) {
  sheetButtons.push({ node, fill });
  if (first) $("sh-open").after(node);
  else document.querySelector("#sheet .sheet-actions").append(node);
}
/** Algo que hacer cada vez que se entra en Servicios. */
export const onShow = (fn) => showHooks.push(fn);
/** El servicio de la ficha abierta (o undefined). */
export const current = () => items.find((x) => x.name === open);
export { closeSheet, load as reload };

const ANSI = /\x1b\[[0-9;?]*[ -\/]*[@-~]|\x1b\][^\x07]*\x07/g;

// "Up 9 days (healthy)" → "activo · 9 días (sano)"
function statusEs(st) {
  const units = { second: "segundo", seconds: "segundos", minute: "minuto", minutes: "minutos", hour: "hora",
    hours: "horas", day: "día", days: "días", week: "semana", weeks: "semanas", month: "mes", months: "meses",
    year: "año", years: "años" };
  return st
    .replace(/\bLess than a second\b/, "0 seconds")
    .replace(/\b(About an?|an?) (hour|minute|second|day|week|month|year)\b/g, "1 $2")
    .replace(/\b(seconds?|minutes?|hours?|days?|weeks?|months?|years?)\b/g, (u) => units[u])
    .replace(/^Up (.*?)( ago)?/, "activo · $1")
    .replace(/^Exited \((\d+)\) (.*) ago/, "parado ($1) · hace $2")
    .replace(/^Created$/, "creado")
    .replace("(healthy)", "(sano)").replace("(unhealthy)", "(enfermo)").replace("(health: starting)", "(arrancando)")
    .replace("Restarting", "reiniciando");
}

function serviceUrl(s) {
  if (s.url) return s.url;
  if (s.port) return `http://${location.hostname}:${s.port}/`;
  return null;
}

function renderList() {
  const q = $("svc-search").value.trim().toLowerCase();
  const match = filter === "down" ? (s) => !s.up : filters[filter]?.match || (() => true);
  const shown = items.filter((s) => match(s) && (!q || s.name.toLowerCase().includes(q) || s.title.toLowerCase().includes(q)));
  if (!shown.length) {
    const msg = (filter === "down" ? "Nada caído 👌" : filters[filter]?.empty?.()) || "Sin resultados";
    $("svc-list").replaceChildren(el("li", { class: "empty" }, msg));
    return;
  }
  $("svc-list").replaceChildren(...shown.map((s) => {
    const icon = el("span", { class: "svc-icon" });
    serviceIcon(icon, s);
    const stats = s.up
      ? [s.cpu != null ? `${s.cpu.toFixed(1)}%` : "", s.mem != null ? fmtBytes(s.mem) : ""].filter(Boolean).join(" · ")
      : "";
    return el("li", {}, el("button", { class: "svc", onclick: () => openSheet(s.name) },
      icon,
      el("div", { class: "svc-main" },
        el("div", { class: "svc-name" }, el("i", { class: `dot ${s.up ? "" : "off"}` }), el("span", {}, s.title),
          s.updating ? el("b", { class: "upd-badge" }, "actualizando…") : s.update ? el("b", { class: "upd-badge" }, "⬆ nueva") : null),
        el("div", { class: "svc-sub" }, statusEs(s.status))),
      el("div", { class: "svc-stats mono" }, stats)));
  }));
}

async function load() {
  try {
    items = await api("/api/containers");
    renderList();
    if (open) fillSheet();
  } catch (e) {
    if (e.message !== "no autenticado") toast(`Servicios: ${e.message}`, true);
  }
}

function setFilter(f) {
  filter = f;
  for (const b of document.querySelectorAll("#view-services .seg-btn")) b.classList.toggle("active", b.dataset.filter === f);
  renderList();
}

function fillSheet() {
  const s = items.find((x) => x.name === open);
  if (!s) return;
  serviceIcon($("sh-icon"), s);
  $("sh-title").textContent = s.title;
  $("sh-status").textContent = `● ${statusEs(s.status)}`;
  $("sh-status").style.color = s.up ? "var(--accent)" : "var(--danger)";
  const url = serviceUrl(s);
  $("sh-open").hidden = !url;
  if (url) $("sh-open").href = url;
  for (const b of sheetButtons) b.fill?.(s);
  $("sh-toggle").textContent = s.up ? "Parar" : "Arrancar";
  $("sh-toggle").classList.toggle("btn-danger", s.up);
}

function flushLogs() {
  if (paused || !pending) return;
  const pre = $("sh-logs");
  const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
  pre.textContent += pending;
  pending = "";
  if (pre.textContent.length > 200000) pre.textContent = pre.textContent.slice(-150000);
  if (atBottom) pre.scrollTop = pre.scrollHeight;
}

function openSheet(name) {
  open = name;
  paused = false;
  pending = "";
  $("sh-pause").textContent = "Pausar";
  $("sh-logs").textContent = "";
  fillSheet();
  $("sheet").hidden = false;
  logWs = new WebSocket(wsUrl(`/ws/logs/${encodeURIComponent(name)}`));
  logWs.onmessage = (e) => { pending += e.data.replace(ANSI, ""); requestAnimationFrame(flushLogs); };
  logWs.onclose = (e) => { if (e.code === 4401) location.reload(); };
}

function closeSheet() {
  open = null;
  $("sheet").hidden = true;
  logWs?.close();
  logWs = null;
}

async function action(verb) {
  const s = items.find((x) => x.name === open);
  if (!s) return;
  if (verb === "stop" && !confirm(`¿Parar ${s.title}?`)) return;
  const btns = document.querySelectorAll(".sheet-actions .btn");
  btns.forEach((b) => (b.disabled = true));
  const label = { start: "Arrancando", stop: "Parando", restart: "Reiniciando" }[verb];
  toast(`${label} ${s.title}…`);
  try {
    await api(`/api/containers/${encodeURIComponent(s.name)}/${verb}`, { method: "POST" });
    toast(`${s.title}: hecho`);
    if (verb !== "stop") {  // los logs del contenedor nuevo
      const name = s.name;
      closeSheet();
      await load();
      openSheet(name);
    } else await load();
  } catch (e) {
    toast(`${s.title}: ${e.message}`, true);
  } finally {
    btns.forEach((b) => (b.disabled = false));
  }
}

export function init() {
  initSheet();
  $("svc-search").addEventListener("input", renderList);
  for (const b of document.querySelectorAll("#view-services .seg-btn")) b.onclick = () => setFilter(b.dataset.filter);
  $("sh-close").onclick = closeSheet;
  $("sheet").addEventListener("click", (e) => { if (e.target.id === "sheet") closeSheet(); });
  $("sh-restart").onclick = () => action("restart");
  $("sh-toggle").onclick = () => {
    const s = items.find((x) => x.name === open);
    action(s?.up ? "stop" : "start");
  };
  $("sh-pause").onclick = () => {
    paused = !paused;
    $("sh-pause").textContent = paused ? "Seguir" : "Pausar";
    flushLogs();
  };
}

export function show(args = []) {
  if (args[0] === "down" || filters[args[0]]) setFilter(args[0]);
  if (args[0] === "open" && args[1]) {  // #services/open/<nombre>: su ficha (p. ej. desde Procesos)
    const name = decodeURIComponent(args[1]);
    (items.length ? Promise.resolve() : load()).then(() => { if (items.some((x) => x.name === name)) openSheet(name); });
  }
  if (timer) return;
  load();
  for (const fn of showHooks) fn();
  timer = setInterval(load, 5000);
}

export function hide() {
  clearInterval(timer);
  timer = null;
}

export function leave() {
  if (open) closeSheet();
  closeUSheet();
}
