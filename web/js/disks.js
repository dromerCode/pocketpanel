// Salud de los discos (SMART) en el widget de Discos: una lucecita por disco y, con el lápiz, el detalle, los avisos
// y los exámenes. Se lee del servidor al entrar en Estado y cada minuto (el servidor lo mira cada 10 min).
import { api, el, toast } from "./api.js";
import { field } from "./modules.js";
import { initSheet, openSheet } from "./ui.js";

const $ = (id) => document.getElementById(id);
let health = null;
let loadedAt = 0;
let onChange = () => {};
const LEVEL = { ok: "Bien", warn: "Ojo", bad: "Fallando", unknown: "Sin datos" };
const name = (dev) => dev.replace("/dev/", "");

const dot = (d) => el("span", {
  class: `light ${d ? d.level : "unknown"}`, role: "img",
  "aria-label": d ? `${name(d.dev)}: ${LEVEL[d.level]}` : "sin datos",
  title: d ? [`${name(d.dev)} · ${LEVEL[d.level]}${d.asleep ? " (dormido)" : ""}`, ...d.problems].join("\n") : "",
});

/** La lucecita del disco donde está montado `mount` (null si no es un disco: mergerfs, red…). */
export function diskDot(mount) {
  const dev = health?.mounts[mount];
  if (!dev) return null;
  return dot(health.disks.find((d) => d.dev === dev));
}

/** Los discos que no salen en la lista (sin montar, o solo con montajes que no se enseñan). */
export function otherDisks(shownMounts) {
  if (!health) return [];
  const shown = new Set(shownMounts.map((m) => health.mounts[m]).filter(Boolean));
  return health.disks.filter((d) => !shown.has(d.dev)).map((d) => el("li", { class: "disk-other" },
    el("div", { class: "disk-row" },
      el("span", { class: "disk-name" }, dot(d), ` ${name(d.dev)}`),
      el("span", { class: "disk-num muted" }, d.model || "sin montar"))));
}

export async function loadHealth(force = false) {
  if (!force && Date.now() - loadedAt < 60_000) return;
  loadedAt = Date.now();
  try {
    health = await api(`/api/disks/health${force ? "?fresh=1" : ""}`);
    onChange();
  } catch { /* sin SMART el widget sigue igual, sin lucecitas */ }
}

const TEST_TYPE = { "short offline": "corto", "extended offline": "largo", "conveyance offline": "de transporte",
  short: "corto", "extended": "largo" };

function ago(d) {
  if (!d.test) return "nunca";
  const type = TEST_TYPE[d.test.type.toLowerCase()] || d.test.type.toLowerCase();
  const result = /without error/i.test(d.test.result) ? "sin errores"
    : /in progress/i.test(d.test.result) ? "en marcha" : /aborted|interrupted/i.test(d.test.result) ? "interrumpido" : d.test.result;
  const h = d.hours != null && d.test.hours != null ? d.hours - d.test.hours : null;
  const when = h == null ? "" : h < 1 ? " · hace menos de 1 h de uso" : h < 48 ? ` · hace ${h} h de uso` : ` · hace ${Math.round(h / 24)} días de uso`;
  return `${type}: ${d.test.passed === false ? "✗ " : ""}${result}${when}`;
}

async function test(d, kind) {
  try {
    await api("/api/disks/test", { method: "POST", body: { dev: d.dev, kind } });
    toast(`Examen ${kind === "short" ? "corto (un par de minutos)" : "largo (unas horas)"} empezado en ${name(d.dev)}`);
    setTimeout(() => loadHealth(true).then(openDetail), 1500);
  } catch (e) {
    toast(e.message, true);
  }
}

function diskCard(d) {
  const facts = [d.temp != null ? `${d.temp}°` : null, d.hours != null ? `${d.hours.toLocaleString("es-ES")} h encendido` : null,
    d.rotational === true ? "disco duro" : d.rotational === false ? "SSD" : null,
    d.crc ? `${d.crc} ${d.crc === 1 ? "error" : "errores"} de cable` : null, d.asleep ? "dormido ahora" : null].filter(Boolean).join(" · ");
  return el("div", { class: "card hd" },
    el("div", { class: "hd-head" }, dot(d), el("b", {}, name(d.dev)), el("span", { class: "muted small" }, d.model || "")),
    facts ? el("div", { class: "muted small mono" }, facts) : null,
    d.problems.length ? el("ul", { class: "hd-problems" }, d.problems.map((p) => el("li", {}, p))) : null,
    d.level !== "unknown" ? el("div", { class: "small" }, d.testing != null ? `Examen en marcha: ${d.testing}% por hacer` : `Último examen ${ago(d)}`) : null,
    d.level !== "unknown" ? el("div", { class: "btn-row" },
      el("button", { class: "btn btn-sm", disabled: d.testing != null, onclick: () => test(d, "short") }, "Examen corto"),
      el("button", { class: "btn btn-sm", disabled: d.testing != null, onclick: () => test(d, "long") }, "Examen largo")) : null);
}

function settingsForm() {
  const s = health.settings;
  const f = {
    notify: field({ type: "bool", label: "Avisar si algo empeora", help: "Sectores dañados, errores de cable, temperatura o un examen que falla" }, s.notify),
    temp_limit: field({ type: "int", label: "Temperatura máxima (°C)" }, s.temp_limit),
    short: field({ type: "choice", label: "Examen corto", choices: ["off", "daily", "weekly"] }, s.short),
    long: field({ type: "choice", label: "Examen largo (lee el disco entero)", choices: ["off", "weekly", "monthly"] }, s.long),
    at: field({ type: "time", label: "A las" }, s.at),
  };
  const NAMES = { off: "Nunca", daily: "Cada día", weekly: "Cada semana (domingo)", monthly: "Cada mes (día 1)" };
  for (const k of ["short", "long"]) for (const o of f[k].node.querySelectorAll("option")) o.textContent = NAMES[o.value];
  const save = async () => {
    try {
      health.settings = await api("/api/disks/health/settings", { method: "PUT",
        body: Object.fromEntries(Object.entries(f).map(([k, x]) => [k, x.get()])) });
      toast("Guardado");
      loadHealth(true);
    } catch (e) {
      toast(e.message, true);
    }
  };
  return el("div", {}, el("h2", { class: "section-title" }, "Avisos y exámenes"),
    el("div", { class: "form" }, Object.values(f).map((x) => x.node)),
    el("p", { class: "muted small" }, "Los exámenes los hace el disco por dentro, sin parar nada. El corto tarda un par de minutos; el largo, horas."),
    el("button", { class: "btn btn-primary", onclick: save }, "Guardar"));
}

function openDetail() {
  if (!health) return toast("Aún no hay datos de los discos", true);
  initSheet();
  openSheet("Salud de los discos", "SMART: lo que dice cada disco de sí mismo",
    !health.sudo ? el("p", { class: "form-error" }, "Sin sudo no se pueden leer los discos: hace falta poder usar smartctl con sudo sin contraseña.") : null,
    ...health.disks.map(diskCard), settingsForm());
}

export function initDisks(rerender) {
  onChange = rerender;
  $("st-disk-edit").onclick = () => loadHealth(true).then(openDetail);
}
