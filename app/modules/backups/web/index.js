// Backups: tarjeta en Estado y «Restaurar config…» en la ficha de cada servicio.
import { api, el, fmtBytes, panel, toast } from "/js/api.js";
import * as services from "/js/services.js";
import { restoreOpen } from "./restore.js";

const $ = (id) => document.getElementById(id);

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

export default {
  styles: ["style.css"],
  cards: [{ slot: "left", html: "card.html", order: 3, slow: loadBackup }],
  init() {
    services.addSheetButton(el("button", { class: "btn", onclick: restoreOpen }, "Restaurar config…"));
  },
};
