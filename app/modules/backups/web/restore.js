// Restaurar la config de una app desde un backup (botón en la ficha de Servicios).
import { api, el, panel, toast } from "/js/api.js";
import * as services from "/js/services.js";
import { closeSheet, openSheet, watchJob } from "/js/ui.js";

function snapLabel(name) {
  const [y, m, d] = name.slice(0, 10).split("-").map(Number);
  const date = new Date(y, m - 1, d).toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short" });
  const tag = name.slice(11);
  const what = !tag ? "diaria" : tag === "manual" ? "manual" : tag.startsWith("antes-restaurar-") ? `antes de restaurar ${tag.slice(16)}`
    : tag.startsWith("antes-") ? `antes de actualizar ${tag.slice(6)}` : tag;
  return `${date} · ${what}`;
}

function watchRestore(app) {
  watchJob(`/api/restore/job/${encodeURIComponent(app)}`, `Restaurando ${app}`,
    { ok: ["✓ restaurado", true], failed: ["✗ falló (los contenedores se han vuelto a arrancar)", false] },
    () => services.reload());
}

export async function restoreOpen() {
  const s = services.current();
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
      result.replaceChildren(el("p", { class: "form-error" }, e.message));
    } finally {
      preview.disabled = false;
    }
  } }, "Ver qué cambiaría");
  go.onclick = async () => {
    if (!confirm(`¿Restaurar ${panel.backups.source}/${app} a la copia "${snapLabel(snap)}"?\n\nAntes hago una copia de lo actual, paro los contenedores que la usan y los vuelvo a arrancar al acabar.`)) return;
    try {
      await api("/api/restore", { method: "POST", body: { snapshot: snap, app } });
      closeSheet();
      watchRestore(app);
    } catch (e) {
      toast(e.message, true);
    }
  };
  services.closeSheet();
  openSheet(`Restaurar ${s.title}`, "volver la config a una copia anterior",
    apps.length > 1 ? el("label", { class: "form" }, el("span", { class: "muted small" }, "Carpeta"), pick(apps.map((a) => [a, a]), app, (v) => { app = v; })) : el("p", { class: "muted small" }, `Carpeta: ${panel.backups.source}/${app}`),
    el("p", { class: "muted small", style: "margin:0" }, "Copia:"),
    pick(snaps.map((n) => [n, snapLabel(n)]), snap, (v) => { snap = v; }),
    el("div", { class: "btn-row" }, preview, go),
    result);
}
