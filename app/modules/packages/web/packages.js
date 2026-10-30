// Paquetes: los del sistema (apt) por actualizar y actualizarlos, en Estado.
import { api, el, fmtAgo, toast } from "/js/api.js";
import { watchJob } from "/js/ui.js";

const $ = (id) => document.getElementById(id);
const DONE = { ok: ["✓ terminado", true], failed: ["✗ falló (ver arriba)", false] };
let openList = false;  // que la lista desplegada no se pliegue al refrescar

function render(p) {
  const badge = $("pkg-badge");
  badge.textContent = p.running ? "Actualizando…" : p.reboot ? "Reiniciar" : p.count ? `${p.count} ${p.count === 1 ? "pendiente" : "pendientes"}` : "Al día";
  badge.className = `badge ${p.running ? "" : p.reboot || p.security ? "warn" : p.count ? "" : "ok"}`;
  $("pkg-sum").replaceChildren(...[
    el("span", {}, p.count ? `${p.count} por actualizar${p.security ? ` · ${p.security} de seguridad` : ""}` : "Todo al día"),
    el("span", { class: "muted small" }, p.checked_at ? `comprobado ${fmtAgo(p.checked_at)}` : ""),
    p.reboot ? el("span", { class: "pkg-reboot" },
      `⟳ Hace falta reiniciar${p.reboot_pkgs.length ? ` (${p.reboot_pkgs.slice(0, 3).join(", ")})` : ""}`) : null,
  ].filter(Boolean));
  const list = p.count ? el("details", { class: "pkg-list", open: openList || null, ontoggle: (e) => { openList = e.target.open; } },
    el("summary", {}, "Ver paquetes"),
    el("ul", {}, p.packages.map((x) => el("li", {},
      el("span", { class: x.security ? "pkg-sec" : "" }, x.name),
      el("span", { class: "pkg-ver mono", title: `${x.from} → ${x.to}` }, x.to))))) : null;
  $("pkg-list").replaceChildren(...(list ? [list] : []));
  const up = $("pkg-up");
  up.hidden = !p.count && !p.running;
  up.textContent = p.running ? "Ver progreso" : `Actualizar (${p.count})`;
  up.onclick = () => (p.running ? watch() : run(true, p.count));
  $("pkg-check").disabled = p.running;
  $("pkg-check").onclick = () => run(false);
}

export async function loadPackages(fresh = false) {
  try {
    render(await api(`/api/packages${fresh ? "?fresh=1" : ""}`));
  } catch (e) {
    if (e.message === "no autenticado") return;
    $("pkg-badge").textContent = "Sin datos";
    $("pkg-badge").className = "badge";
    $("pkg-sum").replaceChildren(el("span", { class: "muted small" }, `No se pudo leer: ${e.message}`));
  }
}

function watch(title = "Paquetes del sistema") {
  watchJob("/api/packages/job", title, DONE, () => loadPackages(true));
}

async function run(upgrade, count) {
  // Buscar no cambia nada; actualizar sí (y en el móvil se toca sin querer), como al actualizar contenedores
  if (upgrade && !confirm(`¿Actualizar ${count} paquetes del sistema (sudo apt upgrade -y)?`)) return;
  try {
    await api("/api/packages/run", { method: "POST", body: { upgrade } });
    watch(upgrade ? "Actualizando paquetes" : "Buscando actualizaciones");
  } catch (e) {
    toast(e.message, true);
  }
}
