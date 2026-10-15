import { api, el, fmtBytes, fmtUptime, has, panel, toast } from "./api.js";
import { renderCharts } from "./charts.js";
import { initActions, loadActions } from "./actions.js";
import { initPush } from "./push.js";

let timer = null;
let slowTimer = null;
let range = "1h";
let lastHistory = [];
const $ = (id) => document.getElementById(id);

function level(pct) { return pct >= 93 ? "bad" : pct >= 85 ? "warn" : ""; }

function render(d) {
  $("st-uptime").textContent = d.uptime != null ? `encendido ${fmtUptime(d.uptime)}` : "";
  $("st-cpu").textContent = d.cpu != null ? `${Math.round(d.cpu)}%` : "…";
  $("st-load").textContent = d.load ? `carga ${d.load.map((x) => x.toFixed(2)).join(" ")}` : "";
  if (d.mem) {
    $("st-mem").textContent = `${Math.round((d.mem.used / d.mem.total) * 100)}%`;
    $("st-mem-sub").textContent = `${fmtBytes(d.mem.used)} / ${fmtBytes(d.mem.total)}`;
  }
  $("st-temp").textContent = d.temp != null ? `${Math.round(d.temp)}°` : "–";
  $("st-up").textContent = d.containers.up;
  const down = $("st-down");
  down.textContent = d.containers.down ? `${d.containers.down} caídos` : "todos en marcha";
  down.classList.toggle("bad", d.containers.down > 0);
  $("st-containers").href = d.containers.down ? "#services/down" : "#services";
  $("st-disks").replaceChildren(...d.disks.map((k) => {
    const name = k.mount.replace(/\/+$/, "").split("/").pop() || "/";
    return el("li", {},
      el("div", { class: "disk-row" },
        el("span", { class: "disk-name" }, name),
        el("span", { class: "disk-num mono" }, `${fmtBytes(k.avail)} libres · ${k.pct}%`)),
      el("div", { class: `bar ${level(k.pct)}` }, el("i", { style: `width:${k.pct}%` })));
  }));
}

async function tick() {
  try {
    render(await api("/api/system"));
  } catch (e) {
    if (e.message !== "no autenticado") toast(`Estado: ${e.message}`, true);
  }
}

async function loadHistory() {
  try {
    lastHistory = await api(`/api/history?range=${range}`);
    renderCharts($("charts"), lastHistory, range);
  } catch (e) {
    if (e.message !== "no autenticado") toast(`Historial: ${e.message}`, true);
  }
}

const RAID_STATUS = {
  ok: ["Limpio", "ok"], degraded: ["Degradado", "bad"], rebuilding: ["Reconstruyendo", "warn"], unknown: ["Sin datos", ""],
};

function renderRaid(r) {
  const [label, cls] = RAID_STATUS[r.status] || RAID_STATUS.unknown;
  const badge = $("raid-badge");
  badge.textContent = r.status === "rebuilding" && r.progress != null ? `${label} ${r.progress}%` : label;
  badge.className = `badge ${cls}`;
  const parts = [];
  if (r.problems?.length) parts.push(el("ul", { class: "raid-problems" }, r.problems.map((p) => el("li", {}, `⚠ ${p}`))));
  if (r.size) {
    parts.push(el("div", {},
      el("div", { class: "disk-row" },
        el("span", {}, `${(r.level || "").toUpperCase()} · ${r.devices.length} discos`),
        el("span", { class: "disk-num mono" }, `${fmtBytes(r.avail)} libres · ${r.pct}%`)),
      el("div", { class: `bar ${level(r.pct)}` }, el("i", { style: `width:${r.pct}%` }))));
  }
  parts.push(el("ul", { class: "raid-disks" }, r.devices.map((d) => {
    const bad = d.health === "FAILED" || d.state.includes("faulty");
    const meta = [d.state, d.temp != null ? `${d.temp}°` : null, d.hours != null ? `${Math.round(d.hours / 24)} días encendido` : null,
      (d.realloc || d.pending) ? `${d.realloc || 0} reasignados · ${d.pending || 0} pendientes` : null,
      d.crc ? `${d.crc} errores CRC (¿cable?)` : null].filter(Boolean).join(" · ");
    return el("li", { class: "raid-disk" },
      el("span", { class: "dev" }, d.dev.replace("/dev/", "")),
      el("span", { class: "model" }, d.model || "?"),
      el("span", { class: `health ${bad ? "bad" : d.health ? "ok" : ""}` }, d.health ? (bad ? "✗ SMART" : "✓ SMART") : "–"),
      el("span", { class: "meta" }, meta));
  })));
  if (r.status === "unknown") parts.push(el("span", { class: "muted small" }, "No se pudo leer el RAID"));
  $("raid").replaceChildren(...parts);
}

async function loadRaid() {
  try {
    renderRaid(await api("/api/raid"));
  } catch (e) {
    $("raid-badge").textContent = "Sin datos";
    $("raid-badge").className = "badge";
    $("raid").replaceChildren(el("span", { class: "muted small" }, `No se pudo leer el RAID: ${e.message}`));
  }
}

function when(ts) {
  const d = new Date(ts * 1000), today = new Date();
  const hm = d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return `hoy ${hm}`;
  const y = new Date(today); y.setDate(today.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `ayer ${hm}`;
  return `${d.toLocaleDateString("es-ES", { day: "numeric", month: "short" })} ${hm}`;
}

function renderBackup(b) {
  const badge = $("bk-badge");
  const ok = b.last_ok, last = b.last;
  const failed = last && !last.ok;
  const stale = ok && Date.now() / 1000 - ok.at > 36 * 3600;
  badge.textContent = b.running ? "Haciendo copia…" : failed ? "Falló" : stale ? "Antigua" : ok ? "Al día" : "Sin copias";
  badge.className = `badge ${b.running ? "warn" : failed ? "bad" : stale ? "warn" : ok ? "ok" : ""}`;
  const rows = [];
  if (ok) {
    rows.push(el("div", { class: "bk-row" }, el("span", {}, "Última copia"), el("span", { class: "mono" }, `${when(ok.at)} · ${ok.seconds} s`)));
    rows.push(el("div", { class: "bk-row" }, el("span", {}, "Tamaño de una copia"), el("span", { class: "mono" }, fmtBytes(ok.size))));
    rows.push(el("div", { class: "bk-row" }, el("span", {}, `${ok.count} copias guardadas`), el("span", { class: "mono" }, `${fmtBytes(ok.total)} en total`)));
  }
  if (ok?.denied) {
    rows.push(el("p", { class: "muted small", style: "margin:0" },
      `⚠ ${ok.denied} archivos no se copian (sin permiso; mira install-root.sh): ${ok.denied_dirs.join(", ")}`));
  }
  if (ok?.changed?.length) {
    rows.push(el("p", { class: "muted small", style: "margin:0" },
      `⚠ No se pudieron copiar porque cambiaban sin parar: ${ok.changed.join(", ")}`));
  }
  if (failed) rows.push(el("ul", { class: "raid-problems" }, el("li", {}, `⚠ ${when(last.at)}: ${last.error}`)));
  rows.push(el("button", { class: "btn btn-sm", disabled: b.running, onclick: backupNow }, b.running ? "Copiando…" : "Hacer copia ahora"));
  const c = panel.backups;
  rows.push(el("span", { class: "muted small" }, `Cada día a las ${c.at} · ${c.source} → ${c.dest} · se guardan ${c.keep_days} días`));
  $("backup").replaceChildren(...rows);
}

async function loadBackup() {
  try {
    renderBackup(await api("/api/backup"));
  } catch (e) {
    if (e.message !== "no autenticado") $("backup").replaceChildren(el("span", { class: "muted small" }, e.message));
  }
}

async function backupNow() {
  try {
    await api("/api/backup", { method: "POST" });
    toast("Copia en marcha; la primera del día tarda más");
    setTimeout(loadBackup, 1000);
  } catch (e) {
    toast(`Backup: ${e.message}`, true);
  }
}

function slowTick() {
  loadHistory();
  if (has("raid")) loadRaid();
  if (has("backups")) loadBackup();
}

export function init() {
  for (const b of document.querySelectorAll("#hist-range .seg-btn")) {
    b.onclick = () => {
      range = b.dataset.range;
      for (const x of document.querySelectorAll("#hist-range .seg-btn")) x.classList.toggle("active", x === b);
      loadHistory();
    };
  }
  new ResizeObserver(() => { if (lastHistory.length) renderCharts($("charts"), lastHistory, range); }).observe($("charts"));
  if (has("actions")) initActions();
  initPush();
}

export function show() {
  if (timer) return;
  tick();
  slowTick();
  if (has("actions")) loadActions();
  timer = setInterval(tick, 5000);
  slowTimer = setInterval(slowTick, 30000);
}

export function hide() {
  clearInterval(timer);
  clearInterval(slowTimer);
  timer = slowTimer = null;
}

export function leave() {
  document.getElementById("run-close").click();
}
