import { api, el, fmtAgo, fmtBytes, serviceIcon, toast, wsUrl } from "./api.js";
import { closeSheet as closeUSheet, initSheet } from "./ui.js";

let items = [];
let units = [];       // servicios de systemd (app/systemd.py): van debajo, tras una línea
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
  node.classList.add("mod-sheet-btn");
  if (first) $("sh-open").after(node);
  else document.querySelector("#sheet .sheet-actions").append(node);
}
/** Algo que hacer cada vez que se entra en Servicios. */
export const onShow = (fn) => showHooks.push(fn);
/** El servicio de la ficha abierta (o undefined). */
export const current = () => items.find((x) => x.name === open);
const find = (name) => items.find((x) => x.name === name) || units.find((x) => x.name === name);
// Parar uno de estos deja al panel sin Docker o sin SSH hasta que se vuelva a arrancar a mano
const VITAL = new Set(["docker.service", "containerd.service", "ssh.service", "sshd.service"]);
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

function unitStatus(u) {
  const ago = u.since ? ` · ${fmtAgo(u.since).replace(/^hace /, u.up ? "desde hace " : "hace ")}` : "";
  if (u.failed) return `falló${u.result && u.result !== "success" ? ` (${u.result})` : ""}${ago}`;
  if (u.up) return `${u.sub === "exited" ? "hecho" : "activo"}${ago}`;
  return `parado${u.enabled === "enabled" ? "" : " · no arranca solo"}${ago}`;
}

function unitRow(u) {
  return el("li", {}, el("button", { class: "svc", onclick: () => openSheet(u.name) },
    el("span", { class: "svc-icon svc-unit-icon" }, "⚙"),
    el("div", { class: "svc-main" },
      el("div", { class: "svc-name" }, el("i", { class: `dot ${u.up ? "" : "off"}` }), el("span", {}, u.title),
        u.scope === "user" ? el("b", { class: "svc-tag" }, "usuario") : null),
      el("div", { class: "svc-sub" }, unitStatus(u))),
    el("div", { class: "svc-stats mono" }, u.mem != null ? fmtBytes(u.mem) : "")));
}

function renderList() {
  const q = $("svc-search").value.trim().toLowerCase();
  const match = filter === "down" ? (s) => !s.up : filters[filter]?.match || (() => true);
  const hit = (s) => !q || s.name.toLowerCase().includes(q) || s.title.toLowerCase().includes(q) || (s.desc || "").toLowerCase().includes(q);
  const shown = items.filter((s) => match(s) && hit(s));
  // los de systemd solo en Todos y Caídos (los filtros de los módulos son cosa de contenedores)
  const shownUnits = filter === "all" || filter === "down" ? units.filter((u) => (filter === "all" || u.failed) && hit(u)) : [];
  if (!shown.length && !shownUnits.length) {
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
  }), ...(shownUnits.length ? [el("li", { class: "svc-sep", role: "separator" }, "Servicios del sistema"), ...shownUnits.map(unitRow)] : []));
}

async function load() {
  try {
    [items, units] = await Promise.all([api("/api/containers"), api("/api/units").catch(() => units)]);
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
  const s = find(open);
  if (!s) return;
  $("sheet").classList.toggle("is-unit", s.kind === "unit");
  if (s.kind === "unit") return fillUnitSheet(s);
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

function fillUnitSheet(u) {
  const icon = $("sh-icon");
  icon.replaceChildren("⚙");
  $("sh-title").textContent = u.title;
  $("sh-status").textContent = `● ${unitStatus(u)}${u.scope === "user" ? " · de usuario" : ""}`;
  $("sh-status").style.color = u.up ? "var(--accent)" : "var(--danger)";
  $("sh-open").hidden = true;
  $("sh-toggle").textContent = u.up ? "Parar" : "Arrancar";
  $("sh-toggle").classList.toggle("btn-danger", u.up);
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
  const u = units.find((x) => x.name === name);
  logWs = new WebSocket(wsUrl(u ? `/ws/unit-logs/${u.scope}/${encodeURIComponent(u.unit)}` : `/ws/logs/${encodeURIComponent(name)}`));
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
  const s = find(open);
  if (!s) return;
  const vital = s.kind === "unit" && VITAL.has(s.unit) && verb !== "start";
  if (vital && !confirm(`${s.title} es lo que usa el panel para llegar al servidor: si ${verb === "stop" ? "lo paras, el panel se queda sin él hasta que lo arranques a mano" : "no vuelve a arrancar, el panel se queda sin él"}.\n\n¿Seguro?`)) return;
  if (!vital && verb === "stop" && !confirm(`¿Parar ${s.title}?`)) return;
  const btns = document.querySelectorAll(".sheet-actions .btn");
  btns.forEach((b) => (b.disabled = true));
  const label = { start: "Arrancando", stop: "Parando", restart: "Reiniciando" }[verb];
  toast(`${label} ${s.title}…`);
  try {
    await api(s.kind === "unit" ? `/api/units/${s.scope}/${encodeURIComponent(s.unit)}/${verb}`
      : `/api/containers/${encodeURIComponent(s.name)}/${verb}`, { method: "POST" });
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
    action(find(open)?.up ? "stop" : "start");
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
