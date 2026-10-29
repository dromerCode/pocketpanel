// Tienda de módulos: activar, desactivar y configurar sin tocar config.yml a mano.
import { api, el, toast } from "./api.js";
import { watchJob } from "./ui.js";

const $ = (id) => document.getElementById(id);
let data = null;

/* ---------- Lista ---------- */

async function load() {
  const downloading = (data?.modules || []).filter((m) => depsBadge(m)?.[1] === "warn").map((m) => m.name);
  try {
    data = await api("/api/modules");
  } catch (e) {
    if (downloading.length) restarting();  // ha terminado y se está reiniciando
    else if (e.message !== "no autenticado") toast(`Módulos: ${e.message}`, true);
    return;
  }
  if (downloading.length && data.modules.every((m) => !downloading.includes(m.name) || m.deps.ready)) restarting();
  else render();
}

// Estado de las dependencias de un módulo activo: [texto de la insignia, clase] o null si no hay nada que contar
function depsBadge(m) {
  if (!m.enabled || !m.deps || m.deps.ready) return null;
  return m.deps.status === "failed" ? ["Falló la descarga", "bad"] : ["Descargando…", "warn"];
}

function render() {
  const g = data.general.values;
  $("mod-general").replaceChildren(el("button", { class: "mod-card mod-general", onclick: openGeneral },
    el("span", { class: "mod-icon" }, "⚙"),
    el("div", { class: "mod-card-desc" }, el("div", { class: "mod-card-title" }, "Ajustes generales"),
      `${g.name} · ${g.timezone} · aviso de disco al ${g.disk_alert_percent}%`)));
  $("mod-grid").replaceChildren(...data.modules.map((m) => {
    const [label, cls] = depsBadge(m) || (m.enabled ? ["Activo", "ok"] : ["Inactivo", ""]);
    return el("button", { class: `mod-card ${m.enabled ? "on" : ""}`, onclick: () => openModule(m) },
  el("div", { class: "mod-card-head" },
    el("span", { class: "mod-icon" }, m.icon),
    el("span", { class: `badge ${cls}` }, label)),
  el("div", { class: "mod-card-title" }, m.title),
  el("div", { class: "mod-card-desc" }, m.desc));
  }));
  if (data.modules.some((m) => depsBadge(m)?.[1] === "warn")) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(load, 3000);  // al terminar, el panel se reinicia solo con el módulo cargado
  }
}
let pollTimer = null;

/* ---------- Dependencias ---------- */

function depsSection(m) {
  if (!m.deps) return null;
  const st = depsBadge(m);
  const text = st ? (st[1] === "bad" ? "La descarga falló." : "Descargando ahora; el módulo aparecerá al terminar.")
    : m.enabled ? "Descargadas." : "Se descargan al activarlo (una sola vez) y se borran al desactivarlo.";
  const watch = () => watchJob(`/api/deps/${m.name}`, `Dependencias de ${m.title}`,
    { ok: ["Listo: reiniciando con el módulo…", true], failed: ["Falló la descarga", false] },
    (j) => { if (j.status === "ok") restarting(); });
  return el("div", {}, el("h2", { class: "section-title" }, "Descargas"),
    el("p", { class: "muted small" }, `${m.deps.packages.join(", ")}. ${text}`),
    m.deps.status ? el("button", { class: "btn btn-sm", onclick: watch }, "Ver descarga") : null,
    st?.[1] === "bad" ? el("button", { class: "btn btn-sm", onclick: async () => {
      await api(`/api/deps/${m.name}/retry`, { method: "POST" });
      watch();
    } }, "Reintentar") : null);
}

/* ---------- Formulario generado del catálogo ---------- */

export function switchInput(checked) {
  const input = el("input", { type: "checkbox", role: "switch" });
  input.checked = !!checked;
  return { node: el("span", { class: "switch" }, input, el("span", {})), input };
}

export function field(f, value) {
  let input, get;
  if (f.type === "bool") {
    const s = switchInput(value);
    return { node: el("label", { class: "inline" }, el("span", {}, f.label, f.help ? el("div", { class: "help" }, f.help) : null), s.node),
      get: () => s.input.checked };
  }
  if (f.type === "list") {
    input = el("textarea", { rows: 3, placeholder: "uno por línea" });
    input.value = (value || []).join("\n");
    get = () => input.value.split("\n").map((x) => x.trim()).filter(Boolean);
  } else if (f.type === "choice") {
    input = el("select", {}, f.choices.map((c) => el("option", { value: c }, c || "(lo que diga tu configuración)")));
    input.value = value ?? "";
    get = () => input.value;
  } else if (f.type === "secret") {
    input = el("input", { type: "password", autocomplete: "new-password",
      placeholder: value?.set ? "•••••• (guardada; escribe para cambiarla)" : "" });
    get = () => input.value;
  } else if (f.type === "int") {
    input = el("input", { type: "number", inputmode: "numeric" });
    input.value = value ?? "";
    get = () => (input.value === "" ? null : Number(input.value));
  } else if (f.type === "time") {
    input = el("input", { type: "time" });
    input.value = value || "";
    get = () => input.value || (f.nullable ? null : "");
  } else {
    input = el("input", { type: "text", autocapitalize: "off", spellcheck: "false" });
    input.value = value ?? "";
    get = () => input.value.trim();
  }
  return { node: el("label", {}, f.label, input, f.help ? el("span", { class: "help" }, f.help) : null), get };
}

function sheet(icon, title, sub, ...body) {
  $("ms-icon").textContent = icon;
  $("ms-title").textContent = title;
  $("ms-sub").textContent = sub || "";
  $("ms-body").replaceChildren(...body);
  $("msheet").hidden = false;
}
const closeSheet = () => { $("msheet").hidden = true; };

/* ---------- Requisitos ---------- */

const MARK = { ok: ["✓", "ck-ok"], warn: ["⚠", "ck-warn"], bad: ["✗", "ck-bad"] };

export function renderChecks(target, checks) {
  if (!checks.length) {
    target.replaceChildren(el("p", { class: "muted small" }, "No necesita nada especial."));
    return;
  }
  target.replaceChildren(el("ul", { class: "checks" }, checks.map((c) => {
    const [mark, cls] = MARK[c.ok ? "ok" : c.level === "warn" ? "warn" : "bad"];
    return el("li", {}, el("span", { class: cls }, mark), el("span", {}, c.label),
      c.detail ? el("span", { class: "ck-detail" }, c.detail) : null);
  })));
}

/* ---------- Fichas ---------- */

function openModule(m) {
  const enabled = switchInput(m.enabled);
  const fields = m.fields.map((f) => [f.key, field(f, m.values[f.key])]);
  const checks = el("div", {});
  const error = el("p", { class: "form-error", role: "alert" });
  const values = () => Object.fromEntries(fields.map(([k, f]) => [k, f.get()]));
  let lastChecks = null;

  async function runChecks() {
    checks.replaceChildren(el("p", { class: "muted small" }, "Comprobando en el servidor…"));
    try {
      lastChecks = await api(`/api/modules/${m.name}/check`, { method: "POST", body: { values: values() } });
      renderChecks(checks, lastChecks);
    } catch (e) {
      checks.replaceChildren(el("p", { class: "form-error" }, e.message));
    }
    return lastChecks || [];
  }

  async function save() {
    error.textContent = "";
    const on = enabled.input.checked;
    if (on) {
      const failing = (await runChecks()).filter((c) => !c.ok && c.level === "error");
      if (failing.length && !confirm(`No se cumple:\n\n${failing.map((c) => `• ${c.label}`).join("\n")}\n\n¿Guardar igualmente?`)) return;
    }
    try {
      await api(`/api/modules/${m.name}`, { method: "PUT", body: { enabled: on, values: values() } });
      closeSheet();
      restarting();
    } catch (e) {
      error.textContent = e.message;
    }
  }

  sheet(m.icon, m.title, m.desc,
    el("div", { class: "switch-row" }, el("b", {}, "Activado"), enabled.node),
    fields.length ? el("div", { class: "form" }, fields.map(([, f]) => f.node)) : null,
    depsSection(m),
    el("div", {}, el("h2", { class: "section-title" }, "Requisitos"), checks,
      el("button", { class: "btn btn-sm", onclick: runChecks }, "Comprobar requisitos")),
    error,
    el("button", { class: "btn btn-primary", onclick: save }, "Guardar y reiniciar"));
  checks.replaceChildren(el("p", { class: "muted small" }, "Pulsa «Comprobar» para ver si el servidor tiene lo necesario."));
}

function openGeneral() {
  const fields = data.general.fields.map((f) => [f.key, field(f, data.general.values[f.key])]);
  const error = el("p", { class: "form-error", role: "alert" });
  async function save() {
    error.textContent = "";
    try {
      await api("/api/settings", { method: "PUT", body: { values: Object.fromEntries(fields.map(([k, f]) => [k, f.get()])) } });
      closeSheet();
      restarting();
    } catch (e) {
      error.textContent = e.message;
    }
  }
  sheet("⚙", "Ajustes generales", "", el("div", { class: "form" }, fields.map(([, f]) => f.node)), error,
    el("button", { class: "btn btn-primary", onclick: save }, "Guardar y reiniciar"));
}

/* ---------- Reinicio ---------- */

async function restarting() {
  $("restarting").hidden = false;
  await new Promise((r) => setTimeout(r, 2000));  // que le dé tiempo a cerrarse
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch("/api/me", { credentials: "same-origin", cache: "no-store" });
      if (r.ok || r.status === 401) { location.reload(); return; }
    } catch { /* aún arrancando */ }
    await new Promise((r) => setTimeout(r, 1000));
  }
  $("restarting-text").textContent = "Tarda demasiado: mira `docker logs pocketpanel` en el servidor.";
}

export function init() {
  $("ms-close").onclick = closeSheet;
  $("msheet").addEventListener("click", (e) => { if (e.target.id === "msheet") closeSheet(); });
}

export function show() {
  load();
}

export function hide() {
  clearTimeout(pollTimer);
}
