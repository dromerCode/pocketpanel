// Paquetes: los del sistema (apt) por actualizar y actualizarlos, en Estado.
import { api, el, fmtAgo, toast } from "/js/api.js";
import { watchJob } from "/js/ui.js";

const $ = (id) => document.getElementById(id);
const DONE = { ok: ["✓ terminado", true], failed: ["✗ falló (ver arriba)", false] };
let openList = false;  // que la lista desplegada no se pliegue al refrescar
const EVERY = 3000;    // mientras apt trabaja, cada cuánto se mira si ha terminado
let follow = null;     // ese temporizador
let doing = null;      // lo que está en marcha: "check", "upgrade" o null
let followed = null;   // lo que se está siguiendo, para el aviso del final (doing ya puede estar a null)
let failed = false;    // la última terminó mal: botón para ver por qué
const HELD = "Ubuntu suelta algunas actualizaciones a los equipos poco a poco (phasing): apt upgrade no las instala "
  + "hasta que le toca a este, normalmente en unos días. No hay que hacer nada.";
const KEPT = "apt upgrade no los instala: piden instalar o quitar otros paquetes (sudo apt full-upgrade) o están retenidos "
  + "con apt-mark hold. No se arregla solo: míralo en la terminal.";

function render(p) {
  doing = p.running ? p.doing || "upgrade" : null;
  if (doing) followed = doing;
  const badge = $("pkg-badge");
  badge.textContent = doing === "check" ? "Buscando…" : doing ? "Actualizando…" : p.reboot ? "Reiniciar" : p.count ? `${p.count} ${p.count === 1 ? "pendiente" : "pendientes"}` : p.kept ? `${p.kept} ${p.kept === 1 ? "retenido" : "retenidos"}` : "Al día";
  badge.className = `badge ${p.running ? "" : p.reboot || p.security || p.kept_security ? "warn" : p.count || p.kept ? "" : "ok"}`;
  $("pkg-sum").replaceChildren(...[
    el("span", {}, p.count ? `${p.count} por actualizar${p.security ? ` · ${p.security} de seguridad` : ""}` : p.kept ? "Nada que instalar" : "Todo al día"),
    p.kept ? el("span", { class: p.kept_security ? "pkg-sec small" : "muted small", title: KEPT }, `${p.kept} ${p.kept === 1 ? "retenido" : "retenidos"}${p.kept_security ? ` · ${p.kept_security} de seguridad` : ""}: apt upgrade no ${p.kept === 1 ? "lo instala" : "los instala"}`) : null,
    p.held ? el("span", { class: "muted small", title: HELD }, `${p.held} en espera (Ubuntu los suelta poco a poco)`) : null,
    el("span", { class: "muted small" }, p.checked_at ? `comprobado ${fmtAgo(p.checked_at)}` : ""),
    p.reboot ? el("span", { class: "pkg-reboot" },
      `⟳ Hace falta reiniciar${p.reboot_pkgs.length ? ` (${p.reboot_pkgs.slice(0, 3).join(", ")})` : ""}`) : null,
  ].filter(Boolean));
  const list = p.packages.length ? el("details", { class: "pkg-list", open: openList || null, ontoggle: (e) => { openList = e.target.open; } },
    el("summary", {}, "Ver paquetes"),
    el("ul", {}, p.packages.map((x) => el("li", { class: x.held || x.kept ? "pkg-held" : "", title: x.held ? HELD : x.kept ? KEPT : null },
      el("span", { class: x.security ? "pkg-sec" : "" }, x.name),
      el("span", { class: "pkg-ver mono", title: `${x.from} → ${x.to}` }, x.held ? "en espera" : x.kept ? "retenido" : x.to))))) : null;
  $("pkg-list").replaceChildren(...(list ? [list] : []));
  // En marcha, el botón de lo que se está haciendo dice «Buscando…» / «Actualizando…» y tocarlo abre la ventana
  const up = $("pkg-up"), check = $("pkg-check");
  up.hidden = !p.count && doing !== "upgrade";
  up.textContent = doing === "upgrade" ? "Actualizando…" : `Actualizar (${p.count})`;
  up.disabled = doing === "check";
  up.onclick = () => (doing === "upgrade" ? watch("Actualizando paquetes") : run(true, p.count));
  check.textContent = doing === "check" ? "Buscando…" : "Buscar";
  check.disabled = doing === "upgrade";
  check.onclick = () => (doing === "check" ? watch("Buscando actualizaciones") : run(false));
  for (const b of [up, check]) {
    b.classList.toggle("busy", b.textContent.endsWith("…"));
    b.title = b.classList.contains("busy") ? "Ver cómo va" : b === check ? "sudo apt update" : "";
  }
  $("pkg-log").hidden = !failed || !!doing;
  $("pkg-log").onclick = () => watch();
  if (doing && !follow) follow = setTimeout(poll, document.hidden ? EVERY * 5 : EVERY);  // bloqueado, sin prisa
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

/** Mientras apt trabaja: al acabar, avisa y relee la lista (la ventana solo se abre si se toca el botón). */
async function poll() {
  let p;
  try {
    p = await api("/api/packages");
  } catch {
    follow = setTimeout(poll, EVERY * 2);
    return;
  }
  follow = null;
  if (p.running) return render(p);  // render vuelve a programar el siguiente
  let j = null;
  try { j = await api("/api/packages/job"); } catch { /* sin registro */ }
  failed = j?.status === "failed";
  const what = followed === "check" ? ["Búsqueda terminada", "La búsqueda ha fallado"] : ["Paquetes actualizados", "La actualización ha fallado"];
  toast(failed ? `${what[1]}: toca «Ver qué ha pasado»` : what[0], failed);
  loadPackages(true);
}

async function run(upgrade, count) {
  // Buscar no cambia nada; actualizar sí (y en el móvil se toca sin querer), como al actualizar contenedores
  if (upgrade && !confirm(`¿Actualizar ${count} paquetes del sistema (sudo apt upgrade -y)?`)) return;
  // la respuesta tarda (va por SSH): que se note ya y un segundo toque no lance otra
  const pressed = $(upgrade ? "pkg-up" : "pkg-check");
  const was = pressed.textContent;
  pressed.textContent = upgrade ? "Actualizando…" : "Buscando…";
  pressed.classList.add("busy");
  $("pkg-up").disabled = $("pkg-check").disabled = true;
  try {
    await api("/api/packages/run", { method: "POST", body: { upgrade } });
    failed = false;
    followed = upgrade ? "upgrade" : "check";
    clearTimeout(follow);
    // por poll y no con solo refrescar: si ya ha terminado (sudo sin permiso falla al instante), también hay que avisar
    await poll();
  } catch (e) {
    toast(e.message, true);
    pressed.textContent = was;
    pressed.classList.remove("busy");
    $("pkg-up").disabled = $("pkg-check").disabled = false;
  }
}
