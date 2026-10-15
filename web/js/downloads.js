// Descargas: qBittorrent (pausar/reanudar) y la cola y los estrenos de Sonarr/Radarr.
import { api, el, fmtBytes, toast } from "./api.js";

const $ = (id) => document.getElementById(id);
let timer = null;

export const speed = (b) => `${fmtBytes(b || 0)}/s`;

function eta(s) {
  if (s == null) return "";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h} h ${m} min` : m ? `${m} min` : "<1 min";
}

function when(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short" });
}

async function toggle(path, msg) {
  try {
    await api(path, { method: "POST" });
    toast(msg);
    setTimeout(load, 700);
  } catch (e) {
    toast(e.message, true);
  }
}

function torrentItem(t) {
  const pct = Math.round(t.progress * 100);
  const meta = t.done ? "completado" : t.paused ? `en pausa · ${pct}%`
    : `${pct}% · ↓ ${speed(t.dl)}${t.eta != null ? ` · quedan ${eta(t.eta)}` : ""}`;
  const verb = t.paused ? "resume" : "pause";
  return el("li", { class: t.paused ? "paused" : "" },
    el("div", { class: "tor-head" },
      el("span", { class: "tor-name" }, t.name),
      t.done ? null : el("button", { class: "btn btn-sm", "aria-label": t.paused ? "Reanudar" : "Pausar",
        onclick: () => toggle(`/api/downloads/torrents/${t.hash}/${verb}`, t.paused ? "Reanudado" : "En pausa") },
      t.paused ? "▶" : "⏸")),
    t.done ? null : el("div", { class: "bar" }, el("i", { style: `width:${pct}%` })),
    el("span", { class: "tor-meta" }, `${meta} · ${fmtBytes(t.size)}`));
}

function render(d) {
  const parts = [];
  if (d.qbit) {
    const active = d.qbit.torrents.filter((t) => !t.done);
    const done = d.qbit.torrents.filter((t) => t.done).slice(0, 10);
    $("dlv-speeds").textContent = d.qbit.transfer ? `↓ ${speed(d.qbit.transfer.dl)} ↑ ${speed(d.qbit.transfer.up)}` : "";
    $("dlv-actions").replaceChildren(
      el("button", { class: "btn", onclick: () => toggle("/api/downloads/pause", "Todo en pausa") }, "⏸ Pausar todo"),
      el("button", { class: "btn", onclick: () => toggle("/api/downloads/resume", "Todo reanudado") }, "▶ Reanudar todo"));
    parts.push(el("h2", { class: "section-title" }, `Descargando (${active.length})`));
    if (d.qbit.error) parts.push(el("p", { class: "form-error" }, d.qbit.error));
    parts.push(active.length ? el("ul", { class: "tor" }, active.map(torrentItem))
      : el("p", { class: "muted small" }, "Nada descargándose ahora mismo."));
    if (done.length) {
      parts.push(el("h2", { class: "section-title" }, "Terminadas hace poco"), el("ul", { class: "tor" }, done.map(torrentItem)));
    }
  } else {
    $("dlv-actions").replaceChildren();
  }
  for (const a of d.arr) {
    const name = a.kind === "sonarr" ? "Sonarr" : "Radarr";
    parts.push(el("h2", { class: "section-title" }, `${name}: en cola (${a.queue.length})`));
    if (a.error) parts.push(el("p", { class: "form-error" }, a.error));
    parts.push(a.queue.length ? el("ul", { class: "up-list" }, a.queue.map((q) => el("li", {},
      el("span", {}, q.title),
      el("span", { class: "when" }, [q.status, q.progress != null ? `${Math.round(q.progress * 100)}%` : null].filter(Boolean).join(" · ")))))
      : el("p", { class: "muted small" }, "Cola vacía."));
    if (a.upcoming.length) {
      parts.push(el("h2", { class: "section-title" }, `${name}: próximos 7 días`),
        el("ul", { class: "up-list" }, a.upcoming.map((u) => el("li", {},
          el("span", {}, `${u.has_file ? "✓ " : ""}${u.title}`), el("span", { class: "when" }, when(u.when))))));
    }
  }
  $("dlv-body").replaceChildren(...parts);
}

async function load() {
  try {
    render(await api("/api/downloads"));
  } catch (e) {
    if (e.message !== "no autenticado") toast(`Descargas: ${e.message}`, true);
  }
}

export function show() {
  load();
  clearInterval(timer);
  timer = setInterval(load, 5000);
}

export function hide() {
  clearInterval(timer);
  timer = null;
}
