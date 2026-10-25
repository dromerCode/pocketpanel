// Actualizaciones: se engancha a Servicios (filtro, botón de buscar, "Actualizar todas" y botón en la ficha).
import { api, el, toast } from "/js/api.js";
import * as services from "/js/services.js";
import { watchJob } from "/js/ui.js";

const info = el("p", { class: "muted small upd-info" });
const all = el("button", { class: "btn btn-primary btn-sm", hidden: true }, "Actualizar todas");
const update = el("button", { class: "btn btn-primary", hidden: true }, "Actualizar");
const DONE = {
  one: { ok: ["✓ actualizado", true], noop: ["ya estaba al día", true], failed: ["✗ falló (se ha vuelto a la versión anterior)", false] },
  all: { ok: ["✓ todo actualizado", true], failed: ["⚠ terminado con fallos (ver arriba)", false] },
};

async function loadInfo() {
  try {
    const u = await api("/api/updates");
    const pending = Object.entries(u.results).filter(([, r]) => r.status === "update").map(([n]) => n).sort();
    const n = pending.length;
    const allRunning = u.jobs.__todas__ === "running";
    all.hidden = !n && !allRunning;
    all.textContent = allRunning ? "Actualizando todas…" : `Actualizar todas (${n})`;
    all.onclick = () => (allRunning ? watch("__todas__", "todas las apps") : updateAll(pending));
    info.textContent = u.checking ? "Buscando actualizaciones…"
      : u.checked_at ? `Actualizaciones: ${n ? `${n} disponibles` : "todo al día"} · comprobado ${new Date(u.checked_at * 1000)
        .toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : "";
  } catch { /* no es crítico */ }
}

function watch(name, label = name) {
  watchJob(`/api/updates/${encodeURIComponent(name)}/job`, `Actualizando ${label}`,
    name === "__todas__" ? DONE.all : DONE.one, () => { loadInfo(); services.reload(); });
}

async function updateAll(names) {
  if (!confirm(`¿Actualizar ${names.length} contenedores?\n\n${names.join(", ")}\n\nHago un backup al principio y los actualizo uno a uno; si alguno no arranca bien, vuelve a su versión anterior y sigo con el resto.`)) return;
  try {
    await api("/api/updates-all", { method: "POST" });
    watch("__todas__", "todas las apps");
  } catch (e) {
    toast(e.message, true);
  }
}

async function updateOpen() {
  const s = services.current();
  if (!s) return;
  if (s.updating) return watch(s.name);
  if (!confirm(`¿Actualizar ${s.title}?\n\nHago un backup de la config, bajo la imagen nueva y recreo el contenedor. Si no arranca bien, vuelvo a la versión anterior.`)) return;
  try {
    await api(`/api/updates/${encodeURIComponent(s.name)}`, { method: "POST" });
    services.closeSheet();
    watch(s.name);
  } catch (e) {
    toast(e.message, true);
  }
}

async function check() {
  try {
    await api("/api/updates/check", { method: "POST" });
    toast("Buscando actualizaciones (tarda un poco)…");
    info.textContent = "Buscando actualizaciones…";
    setTimeout(() => { services.reload(); loadInfo(); }, 20000);
  } catch (e) {
    toast(e.message, true);
  }
}

export default {
  styles: ["style.css"],
  init() {
    services.addFilter("updates", "Actualizar", (s) => s.update || s.updating,
      () => (info.textContent ? "Todo al día 👌" : "Aún no se han buscado actualizaciones (⟳)"));
    services.addHeader(el("button", { class: "icon-btn", title: "Buscar actualizaciones",
      "aria-label": "Buscar actualizaciones", onclick: check }, "⟳"));
    services.addInfo(el("div", { class: "upd-row" }, info, all));
    update.onclick = updateOpen;
    services.addSheetButton(update, (s) => {
      update.hidden = !(s.update || s.updating);
      update.textContent = s.updating ? "Actualizando…" : "Actualizar";
    }, true);
    services.onShow(loadInfo);
  },
};
