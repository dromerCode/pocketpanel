import { api, el, fmtBytes, has, panel, serviceIcon, toast, wsUrl } from "./api.js";
import { closeSheet as closeUSheet, initSheet, openSheet as openUSheet } from "./ui.js";

let items = [];
let filter = "all";
let timer = null;
let open = null;      // servicio de la ficha abierta
let logWs = null;
let paused = false;
let pending = "";
const $ = (id) => document.getElementById(id);

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
  const shown = items.filter((s) =>
    (filter === "all" || (filter === "down" && !s.up) || (filter === "updates" && (s.update || s.updating))) && (!q || s.name.toLowerCase().includes(q) || s.title.toLowerCase().includes(q)));
  if (!shown.length) {
    const msg = { down: "Nada caído 👌", updates: $("upd-info").textContent ? "Todo al día 👌" : "Aún no se han buscado actualizaciones (⟳)" }[filter] || "Sin resultados";
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
  $("sh-update").hidden = !(s.update || s.updating);
  $("sh-update").textContent = s.updating ? "Actualizando…" : "Actualizar";
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

/* ---------- Restaurar config desde un backup ---------- */

function snapLabel(name) {
  const [y, m, d] = name.slice(0, 10).split("-").map(Number);
  const date = new Date(y, m - 1, d).toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short" });
  const tag = name.slice(11);
  const what = !tag ? "diaria" : tag === "manual" ? "manual" : tag.startsWith("antes-restaurar-") ? `antes de restaurar ${tag.slice(16)}`
    : tag.startsWith("antes-") ? `antes de actualizar ${tag.slice(6)}` : tag;
  return `${date} · ${what}`;
}

function watchRestore(app) {
  $("run-title").textContent = `Restaurando ${app}`;
  $("run-out").textContent = "";
  $("run-status").textContent = "en marcha… (puedes cerrar esto, sigue en el servidor)";
  $("run-status").style.color = "";
  $("runner").hidden = false;
  clearInterval(jobTimer);
  const poll = async () => {
    try {
      const j = await api(`/api/restore/job/${encodeURIComponent(app)}`);
      $("run-out").textContent = j.lines.join("\n");
      $("run-out").scrollTop = $("run-out").scrollHeight;
      if (j.status !== "running") {
        clearInterval(jobTimer);
        $("run-status").textContent = j.status === "ok" ? "✓ restaurado" : "✗ falló (los contenedores se han vuelto a arrancar)";
        $("run-status").style.color = j.status === "ok" ? "var(--accent)" : "var(--danger)";
        load();
      }
    } catch (e) {
      $("run-status").textContent = `sin conexión, reintento… (${e.message})`;
    }
  };
  poll();
  jobTimer = setInterval(poll, 1500);
}

async function restoreOpen() {
  const s = items.find((x) => x.name === open);
  if (!s) return;
  let apps, snaps;
  try {
    [apps, snaps] = await Promise.all([api(`/api/restore/apps/${encodeURIComponent(s.name)}`), api("/api/restore/snapshots")]);
  } catch (e) {
    return toast(e.message, true);
  }
  if (!apps.length) return toast(`${s.title} no guarda su config en ${panel.backups.source}`, true);
  if (!snaps.length) return toast("Todavía no hay copias completas para restaurar (la primera se hace esta noche)", true);
  let app = apps[0], snap = snaps[0];
  const result = el("div", {});
  const go = el("button", { class: "btn btn-danger", hidden: true }, "Restaurar");
  const pick = (opts, cur, set) => {
    const box = el("div", { class: "chips" });
    const draw = (v) => box.replaceChildren(...opts.map(([val, label]) =>
      el("button", { type: "button", class: val === v ? "on" : "", onclick: () => { set(val); draw(val); result.replaceChildren(); go.hidden = true; } }, label)));
    draw(cur);
    return box;
  };
  const preview = el("button", { class: "btn", onclick: async () => {
    preview.disabled = true;
    result.replaceChildren(el("p", { class: "muted small" }, "Comparando con la copia…"));
    try {
      const p = await api("/api/restore/preview", { method: "POST", body: { snapshot: snap, app } });
      result.replaceChildren(...[
        el("p", {}, p.changes ? `Se cambiarían ${p.changes} archivos de ${panel.backups.source}/${app}.` : "No hay diferencias: ya está igual que en la copia."),
        p.files.length ? el("pre", { class: "logs mono", style: "max-height:180px" }, p.files.join("\n")) : null].filter(Boolean));
      go.hidden = !p.changes;
    } catch (e) {
      result.replaceChildren(el("p", { class: "u-disabled" }, e.message));
    } finally {
      preview.disabled = false;
    }
  } }, "Ver qué cambiaría");
  go.onclick = async () => {
    if (!confirm(`¿Restaurar ${panel.backups.source}/${app} a la copia "${snapLabel(snap)}"?\n\nAntes hago una copia de lo actual, paro los contenedores que la usan y los vuelvo a arrancar al acabar.`)) return;
    try {
      await api("/api/restore", { method: "POST", body: { snapshot: snap, app } });
      closeUSheet();
      watchRestore(app);
    } catch (e) {
      toast(e.message, true);
    }
  };
  closeSheet();
  openUSheet(`Restaurar ${s.title}`, "volver la config a una copia anterior",
    apps.length > 1 ? el("label", { class: "form" }, el("span", { class: "muted small" }, "Carpeta"), pick(apps.map((a) => [a, a]), app, (v) => { app = v; })) : el("p", { class: "muted small" }, `Carpeta: ${panel.backups.source}/${app}`),
    el("p", { class: "muted small", style: "margin:0" }, "Copia:"),
    pick(snaps.map((n) => [n, snapLabel(n)]), snap, (v) => { snap = v; }),
    el("div", { class: "btn-row" }, preview, go),
    result);
}

/* ---------- Actualizaciones ---------- */

let jobTimer = null;

async function loadUpdatesInfo() {
  try {
    const u = await api("/api/updates");
    const pending = Object.entries(u.results).filter(([, r]) => r.status === "update").map(([n]) => n).sort();
    const n = pending.length;
    const allRunning = u.jobs.__todas__ === "running";
    $("upd-all").hidden = !n && !allRunning;
    $("upd-all").textContent = allRunning ? "Actualizando todas…" : `Actualizar todas (${n})`;
    $("upd-all").onclick = () => (allRunning ? watchJob("__todas__", "todas las apps") : updateAll(pending));
    $("upd-info").textContent = u.checking ? "Buscando actualizaciones…"
      : u.checked_at ? `Actualizaciones: ${n ? `${n} disponibles` : "todo al día"} · comprobado ${new Date(u.checked_at * 1000)
        .toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : "";
  } catch { /* no es crítico */ }
}

async function updateAll(names) {
  if (!confirm(`¿Actualizar ${names.length} contenedores?\n\n${names.join(", ")}\n\nHago un backup al principio y los actualizo uno a uno; si alguno no arranca bien, vuelve a su versión anterior y sigo con el resto.`)) return;
  try {
    await api("/api/updates-all", { method: "POST" });
    watchJob("__todas__", "todas las apps");
  } catch (e) {
    toast(e.message, true);
  }
}

function watchJob(name, label = name) {
  $("run-title").textContent = `Actualizando ${label}`;
  $("run-out").textContent = "";
  $("run-status").textContent = "en marcha… (puedes cerrar esto, sigue en el servidor)";
  $("run-status").style.color = "";
  $("runner").hidden = false;
  clearInterval(jobTimer);
  const poll = async () => {
    try {
      const j = await api(`/api/updates/${encodeURIComponent(name)}/job`);
      $("run-out").textContent = j.lines.join("\n");
      $("run-out").scrollTop = $("run-out").scrollHeight;
      if (j.status !== "running") {
        clearInterval(jobTimer);
        const msg = name === "__todas__"
          ? { ok: "✓ todo actualizado", failed: "⚠ terminado con fallos (ver arriba)" }[j.status]
          : { ok: "✓ actualizado", noop: "ya estaba al día", failed: "✗ falló (se ha vuelto a la versión anterior)" }[j.status];
        if (has("updates")) loadUpdatesInfo();
        $("run-status").textContent = msg;
        $("run-status").style.color = j.status === "failed" ? "var(--danger)" : "var(--accent)";
        load();
      }
    } catch (e) {
      $("run-status").textContent = `sin conexión, reintento… (${e.message})`;
    }
  };
  poll();
  jobTimer = setInterval(poll, 1500);
}

async function updateOpen() {
  const s = items.find((x) => x.name === open);
  if (!s) return;
  if (s.updating) return watchJob(s.name);
  if (!confirm(`¿Actualizar ${s.title}?\n\nHago un backup de la config, bajo la imagen nueva y recreo el contenedor. Si no arranca bien, vuelvo a la versión anterior.`)) return;
  try {
    await api(`/api/updates/${encodeURIComponent(s.name)}`, { method: "POST" });
    closeSheet();
    watchJob(s.name);
  } catch (e) {
    toast(e.message, true);
  }
}

async function checkUpdates() {
  try {
    await api("/api/updates/check", { method: "POST" });
    toast("Buscando actualizaciones (tarda un poco)…");
    $("upd-info").textContent = "Buscando actualizaciones…";
    setTimeout(() => { load(); loadUpdatesInfo(); }, 20000);
  } catch (e) {
    toast(e.message, true);
  }
}

export function init() {
  $("sh-update").onclick = updateOpen;
  $("sh-restore").onclick = restoreOpen;
  initSheet();
  $("upd-check").onclick = checkUpdates;
  document.getElementById("run-close").addEventListener("click", () => clearInterval(jobTimer));
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
  if (args[0] === "down" || args[0] === "updates") setFilter(args[0]);
  if (timer) return;
  load();
  if (has("updates")) loadUpdatesInfo();
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
