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
  let input, get, set;
  const hint = el("span", { class: "suggest", hidden: true });
  const api_ = (node) => ({ node, get, set, hint, secret: f.type === "secret", saved: f.type === "secret" && !!value?.set });
  if (f.type === "bool") {
    const s = switchInput(value);
    get = () => s.input.checked;
    set = (v) => { s.input.checked = !!v; };
    return api_(el("label", { class: "inline" }, el("span", {}, f.label, f.help ? el("div", { class: "help" }, f.help) : null, hint), s.node));
  }
  if (f.type === "list") {
    input = el("textarea", { rows: 3, placeholder: "uno por línea" });
    input.value = (value || []).join("\n");
    get = () => input.value.split("\n").map((x) => x.trim()).filter(Boolean);
    set = (v) => { input.value = v.join("\n"); input.rows = Math.min(10, Math.max(3, v.length)); };
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
  set ??= (v) => { input.value = v ?? ""; };
  return api_(el("label", {}, f.label, input, f.help ? el("span", { class: "help" }, f.help) : null, hint));
}

/* ---------- Sugerencias: lo que se averigua mirando el servidor (app/suggest.py) ---------- */

const fmtValue = (v) => (Array.isArray(v) ? v.join(", ") : v === true ? "sí" : String(v));
const isEmpty = (v) => v == null || v === "" || v === false || (Array.isArray(v) && !v.length);

/** Rellena `fields` ([[clave, campo]]) con `sugg`. En un módulo apagado (o recién instalado) rellena todo; en uno
 * que ya funciona solo lo vacío, y en lo demás ofrece el valor encontrado con un botón. Devuelve cuántos ha rellenado. */
export function applySuggestions(fields, sugg, configured) {
  let n = 0;
  for (const [k, f] of fields) {
    const s = sugg[k];
    if (!s) continue;
    if (!f.secret && JSON.stringify(f.get()) === JSON.stringify(s.value)) continue;  // ya está bien
    if (!configured || (isEmpty(f.get()) && !f.saved)) {
      f.set(s.value);
      f.hint.replaceChildren(`✨ Encontrado: ${s.why}`);
      f.hint.hidden = false;
      n++;
    } else if (Array.isArray(s.value)) {
      // Una lista que ya tiene lo suyo: solo se ofrece añadir lo que falte, nunca quitar
      const cur = f.get();
      const missing = s.value.filter((x) => !cur.includes(x));
      if (!missing.length) continue;
      const add = el("button", { type: "button", class: "suggest-use", onclick: (e) => {
        e.preventDefault();
        f.set([...f.get(), ...missing.filter((x) => !f.get().includes(x))]);
        f.hint.replaceChildren(`✨ Añadido: ${s.why}`);
      } }, "Añadir");
      f.hint.replaceChildren(`✨ También hay ${fmtValue(missing)} (${s.why}) `, add);
      f.hint.hidden = false;
    } else {
      const use = el("button", { type: "button", class: "suggest-use", onclick: (e) => {
        e.preventDefault();
        f.set(s.value);
        f.hint.replaceChildren(`✨ Encontrado: ${s.why}`);
      } }, "Usar");
      f.hint.replaceChildren(f.secret ? `✨ Hay una en el servidor (${s.why}) ` : `✨ En el servidor: ${fmtValue(s.value)} (${s.why}) `, use);
      f.hint.hidden = false;
    }
  }
  return n;
}

function sheet(icon, title, sub, ...body) {
  $("ms-icon").textContent = icon;
  $("ms-title").textContent = title;
  $("ms-sub").textContent = sub || "";
  $("ms-body").replaceChildren(...body.filter((x) => x != null));
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

  const found = el("p", { class: "suggest-status muted small", hidden: !fields.length }, "Buscando en el servidor qué rellenar…");
  if (fields.length) {
    api(`/api/modules/${m.name}/suggest`).then((sugg) => {
      const n = applySuggestions(fields, sugg, m.enabled);
      const offered = Object.keys(sugg).length;
      found.hidden = !offered;
      found.textContent = n ? `✨ He rellenado ${n === 1 ? "un campo" : `${n} campos`} con lo que hay en el servidor: revísalo antes de guardar.`
        : "✨ Lo he comparado con lo que hay en el servidor.";
    }).catch(() => { found.hidden = true; });
  }

  sheet(m.icon, m.title, m.desc,
    el("div", { class: "switch-row" }, el("b", {}, "Activado"), enabled.node),
    found,
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
