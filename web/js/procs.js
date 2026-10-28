// El widget Procesos de Estado: cerrado no pide nada; abierto pide /api/processes cada 5 s. Se cierra solo al salir
// de Estado (o al dejar la app en segundo plano), así no queda nada leyendo /proc a escondidas.
import { api, el, fmtBytes, toast } from "./api.js";

const $ = (id) => document.getElementById(id);
const EVERY = 5000;
let timer = null;
let sort = "cpu";
let busy = false;
let qTimer = null;

const isOpen = () => $("pr-toggle").getAttribute("aria-expanded") === "true";
const cpuLevel = (pct) => (pct >= 90 ? "bad" : pct >= 40 ? "warn" : "");  // 100 % = un núcleo

function render(d) {
  const shown = d.shown < d.count ? `${d.shown} de ${d.count}` : `${d.count}`;
  $("pr-sum").textContent = `${shown} procesos · ${d.ncpu} núcleos`;
  const rows = d.procs.map((p) => el("li", { class: "pr-row", title: `${p.pid} · ${p.user}\n${p.cmd}` },
    el("span", { class: "pr-name" }, p.name),
    el("span", { class: `pr-cpu mono ${p.cpu == null ? "" : cpuLevel(p.cpu)}` }, p.cpu == null ? "…" : `${p.cpu.toFixed(1)}%`),
    el("span", { class: "pr-mem mono" }, fmtBytes(p.mem)),
    el("span", { class: "pr-cmd mono" }, `${p.pid} · ${p.user} · ${p.cmd}`)));
  $("pr-list").replaceChildren(...(rows.length ? rows : [el("li", { class: "pr-empty muted" }, "Nada coincide")]));
}

async function load() {
  if (busy) return;  // con el host lento no se apilan peticiones
  busy = true;
  try {
    const q = $("pr-q").value.trim();
    const d = await api(`/api/processes?sort=${sort}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
    if (isOpen()) render(d);
  } catch (e) {
    if (e.message !== "no autenticado") toast(`Procesos: ${e.message}`, true);
  } finally {
    busy = false;
  }
}

function setOpen(open) {
  $("pr-toggle").setAttribute("aria-expanded", String(open));
  $("pr-body").hidden = $("pr-sort").hidden = !open;
  clearInterval(timer);
  timer = null;
  if (open) {
    $("pr-sum").textContent = "midiendo…";
    load();
    timer = setInterval(load, EVERY);
  } else {
    $("pr-list").replaceChildren();
  }
}

export function initProcs() {
  $("pr-toggle").onclick = () => setOpen(!isOpen());
  for (const b of document.querySelectorAll("#pr-sort .seg-btn")) {
    b.onclick = () => {
      sort = b.dataset.sort;
      for (const x of document.querySelectorAll("#pr-sort .seg-btn")) x.classList.toggle("active", x === b);
      load();
    };
  }
  $("pr-q").oninput = () => { clearTimeout(qTimer); qTimer = setTimeout(load, 300); };
}

export function closeProcs() {
  if (isOpen()) setOpen(false);
}
