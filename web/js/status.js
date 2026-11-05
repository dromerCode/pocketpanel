import { api, el, fmtBytes, fmtUptime, toast } from "./api.js";
import { renderCharts } from "./charts.js";
import { initPush } from "./push.js";
import { closeProcs, initProcs } from "./procs.js";
import { diskDot, initDisks, loadHealth, otherDisks } from "./disks.js";
import { cards } from "./registry.js";
import { initTailscale, loadTailscale } from "./tailscale.js";
import { initWidgets, layoutReady, leaveWidgets } from "./widgets.js";

let timer = null;
let slowTimer = null;
let range = "1h";
let lastHistory = [];
let lastSystem = null;
const $ = (id) => document.getElementById(id);

export function level(pct) { return pct >= 93 ? "bad" : pct >= 85 ? "warn" : ""; }

function render(d) {
  lastSystem = d;
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
  down.textContent = d.containers.down ? `${d.containers.down} ${d.containers.down === 1 ? "caído" : "caídos"}` : "todos en marcha";
  down.classList.toggle("bad", d.containers.down > 0);
  $("st-containers").href = d.containers.down ? "#services/down" : "#services";
  $("st-disks").replaceChildren(...d.disks.map((k) => {
    const name = k.mount.replace(/\/+$/, "").split("/").pop() || "/";
    return el("li", {},
      el("div", { class: "disk-row" },
        el("span", { class: "disk-name" }, diskDot(k.mount), diskDot(k.mount) ? ` ${name}` : name),
        el("span", { class: "disk-num mono" }, `${fmtBytes(k.avail)} libres · ${k.pct}%`)),
      el("div", { class: `bar ${level(k.pct)}` }, el("i", { style: `width:${k.pct}%` })));
  }), ...otherDisks(d.disks.map((k) => k.mount)));
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

// Lo que se oculta en «Organizar» no pide nada; al volver a sacarlo, se pone al día (evento wshow, widgets.js).
// Lo lento del propio Estado, por widget (Tailscale lo mira él mismo, en tailscale.js):
const widget = (id) => document.querySelector(`#st-grid > [data-w="${id}"]`);
const SLOW = { history: () => loadHistory(), disks: () => loadHealth() };

// Las tarjetas de los módulos (registry.js): show al entrar, fast con cada tick y slow cada 30 s
const each = async (pick) => {
  await layoutReady;  // hasta entonces no se sabe cuáles están ocultas
  for (const c of cards()) if (!c.box?.hidden) pick(c)?.();
};

let slowAt = 0;
async function slowTick(entering = false) {
  slowAt = Date.now();
  loadTailscale();
  // al entrar, las que tienen show lo usan en vez de slow (si no, se pedía todo dos veces)
  each((c) => (entering ? c.show ?? c.slow ?? c.fast : c.slow));
  await layoutReady;
  for (const [id, load] of Object.entries(SLOW)) if (!widget(id)?.hidden) load();
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
  initPush();
  initWidgets();
  initProcs();
  initDisks(() => { if (lastSystem) render(lastSystem); });
  initTailscale();
  for (const c of cards()) c.init?.();
  for (const [id, load] of Object.entries(SLOW)) widget(id)?.addEventListener("wshow", load);  // (módulos: registry.js)
}

export function show() {
  if (timer) return;
  tick();
  // Lo lento (historial, discos, Tailscale y el slow de las tarjetas) solo si hace más de 30 s: volver al panel
  // desde otra app al momento no lo vuelve a pedir todo. El show de cada tarjeta sí, que es su «al entrar».
  if (Date.now() - slowAt >= 30_000) slowTick(true);
  else each((c) => c.show ?? c.fast);
  timer = setInterval(() => { tick(); each((c) => c.fast); }, 5000);
  slowTimer = setInterval(() => slowTick(), 30_000);
}

export function hide() {
  clearInterval(timer);
  clearInterval(slowTimer);
  timer = slowTimer = null;
  closeProcs();
}

export function leave() {
  leaveWidgets();
  document.getElementById("run-close").click();
}
