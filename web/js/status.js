import { api, el, fmtBytes, fmtUptime, toast } from "./api.js";
import { renderCharts } from "./charts.js";
import { initPush } from "./push.js";
import { cards } from "./registry.js";

let timer = null;
let slowTimer = null;
let range = "1h";
let lastHistory = [];
const $ = (id) => document.getElementById(id);

export function level(pct) { return pct >= 93 ? "bad" : pct >= 85 ? "warn" : ""; }

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
  down.textContent = d.containers.down ? `${d.containers.down} ${d.containers.down === 1 ? "caído" : "caídos"}` : "todos en marcha";
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

// Las tarjetas de los módulos (registry.js): show al entrar, fast con cada tick y slow cada 30 s
const each = (hook) => { for (const c of cards()) c[hook]?.(); };

function slowTick() {
  loadHistory();
  each("slow");
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
  each("init");
}

export function show() {
  if (timer) return;
  tick();
  slowTick();
  each("show");
  timer = setInterval(() => { tick(); each("fast"); }, 5000);
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
