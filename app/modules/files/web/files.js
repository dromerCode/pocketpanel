// Archivos: navegar, seleccionar, portapapeles (copiar/cortar → pegar en otra carpeta), subir, descargar y un
// visor/editor sencillo. La ruta va en el hash (#files/<ruta>) para que «atrás» del móvil suba de carpeta.
//
// Con ratón: clic selecciona (Ctrl/⌘ suma, Mayús un rango), doble clic abre. Con el dedo: tocar abre, mantener
// pulsado (o tocar el icono) selecciona y, con algo seleccionado, tocar suma o quita. Teclado: Ctrl+A/C/X/V, Supr,
// F2, Intro, Retroceso y Esc.
import { api, el, fmtBytes, toast } from "/js/api.js";
import { watchJob } from "/js/ui.js";

const $ = (id) => document.getElementById(id);
const fine = matchMedia("(pointer: fine)");
// ¿ratón? Lo dice cada clic (pointerType); si no lo trae (un click() de teclado/lector), el puntero principal
const mouse = (ev) => (ev.pointerType ? ev.pointerType === "mouse" : fine.matches);
const CLIP_KEY = "fm-clip";
const HIDDEN_KEY = "fm-hidden";

let roots = [];
let cur = null;          // lo último de /api/files/list
let items = [];          // lo que se ve (filtrado)
const sel = new Set();   // nombres seleccionados
let anchor = null;       // para Mayús+clic
let clip = load(CLIP_KEY, null);  // { op: "copy" | "cut", paths, from }
let showHidden = load(HIDDEN_KEY, false);
let busy = false;

function load(k, d) { try { return JSON.parse(sessionStorage.getItem(k)) ?? d; } catch { return d; } }
function store(k, v) { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } }

const join = (d, n) => `${d.replace(/\/$/, "")}/${n}`;
const url = (path, inline) => `/api/files/download?path=${encodeURIComponent(path)}${inline ? "&inline=1" : ""}`;
const go = (path) => { location.hash = `#files/${encodeURIComponent(path)}`; };
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// --- iconos -----------------------------------------------------------------------------------------------
const KINDS = {
  image: /\.(jpe?g|png|gif|webp|avif|bmp|svg|heic|tiff?)$/i,
  video: /\.(mp4|mkv|webm|mov|avi|m4v|ts|wmv)$/i,
  audio: /\.(mp3|flac|ogg|opus|m4a|wav|aac)$/i,
  archive: /\.(zip|tar|gz|tgz|bz2|xz|zst|7z|rar|iso|deb)$/i,
  pdf: /\.pdf$/i,
  text: /(\.(txt|md|log|ya?ml|json|toml|ini|conf|cfg|env|sh|py|js|mjs|ts|css|html?|xml|csv|srt|sub|nfo|service|timer|sql|go|rs|c|h|cpp|java|php|rb|lua|properties)|^\.?[a-z]*rc|^dockerfile|^makefile|^readme|^license|^\.gitignore|^\.env.*)$/i,
};
function kind(e) {
  if (e.dir) return "dir";
  for (const [k, re] of Object.entries(KINDS)) if (re.test(e.name)) return k;
  return "file";
}
const NS = "http://www.w3.org/2000/svg";
function icon(k) {
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(NS, "path");
  p.setAttribute("d", k === "dir"
    ? "M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l2 2h8.4A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z"
    : "M6.5 3h7.5l4.5 4.5v12a1.5 1.5 0 0 1-1.5 1.5h-10.5a1.5 1.5 0 0 1-1.5-1.5v-15a1.5 1.5 0 0 1 1.5-1.5zM14 3v4.5h4.5");
  s.append(p);
  return el("span", { class: `fm-ico ico-${k}` }, s,
    k !== "dir" && k !== "file" ? el("b", {}, { image: "IMG", video: "VID", audio: "AUD", archive: "ZIP", pdf: "PDF", text: "TXT" }[k]) : null);
}

function when(t) {
  if (!t) return "";
  const d = new Date(t * 1000), now = new Date();
  if (d.toDateString() === now.toDateString()) return `hoy ${d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}`;
  return d.toLocaleDateString("es-ES", { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
}

// --- listado -----------------------------------------------------------------------------------------------
async function open(path, keepSel = false) {
  if (!roots.length) {
    try {
      roots = (await api("/api/files/roots")).roots;
    } catch (e) {
      return fail(e);
    }
    $("fm-root").replaceChildren(...roots.map((r) => el("option", { value: r.path }, r.name === "Inicio" ? `Inicio (${r.path})` : r.path)));
    if (!roots.length) return fail(new Error("ninguna carpeta de inicio existe: revísalas en Módulos → Archivos"));
  }
  path ||= cur?.path || roots[0].path;
  try {
    const d = await api(`/api/files/list?path=${encodeURIComponent(path)}`);
    if (!keepSel || d.path !== cur?.path) { sel.clear(); anchor = null; $("fm-filter").value = ""; }
    if (d.path !== cur?.path) $("fm-wrap").scrollTop = 0;
    cur = d;
    for (const n of [...sel]) if (!d.items.some((e) => e.name === n)) sel.delete(n);
    render();
  } catch (e) {
    if (cur && path !== cur.path) { toast(e.message, true); go(cur.path); return; }
    if (path !== roots[0].path) { toast(e.message, true); go(roots[0].path); return; }
    fail(e);
  }
}

function fail(e) {
  if (e.message === "no autenticado") return;
  $("fm-list").replaceChildren(el("li", { class: "fm-empty form-error" }, e.message));
}

function render() {
  const q = $("fm-filter").value.trim().toLowerCase();
  items = cur.items.filter((e) => (showHidden || !e.name.startsWith(".")) && (!q || e.name.toLowerCase().includes(q)));
  $("fm-root").value = cur.root;
  $("fm-up").disabled = !cur.parent;
  crumbs();
  $("fm-list").replaceChildren(...(items.length ? items.map(row)
    : [el("li", { class: "fm-empty muted" }, q ? "Nada coincide con el filtro." : "Carpeta vacía.")]));
  const hiddenN = cur.items.filter((e) => e.name.startsWith(".")).length;
  $("fm-info").textContent = [plural(items.length, "elemento", "elementos"),
    !showHidden && hiddenN ? `${hiddenN} ocultos` : null,
    cur.truncated ? "solo los 5000 primeros" : null,
    cur.free ? `${fmtBytes(cur.free.free)} libres` : null].filter(Boolean).join(" · ");
  bars();
}

function crumbs() {
  const root = cur.root, rel = cur.path.slice(root.length).split("/").filter(Boolean);
  const rootName = roots.find((r) => r.path === root)?.name || root;
  const parts = [[rootName, root]];
  rel.forEach((p, i) => parts.push([p, join(root, rel.slice(0, i + 1).join("/"))]));
  const nav = $("fm-crumbs");
  nav.replaceChildren(...parts.flatMap(([name, p], i) => [
    i ? el("span", { class: "fm-sep", "aria-hidden": "true" }, "/") : null,
    el("a", { href: `#files/${encodeURIComponent(p)}`, class: i === parts.length - 1 ? "on" : null }, name),
  ].filter(Boolean)));
  nav.scrollLeft = nav.scrollWidth;
}

function row(e) {
  const k = kind(e);
  const cut = clip?.op === "cut" && clip.paths.includes(join(cur.path, e.name));
  const li = el("li", { class: `fm-row${sel.has(e.name) ? " sel" : ""}${cut ? " cut" : ""}`, role: "option",
    "aria-selected": sel.has(e.name) ? "true" : "false", "data-name": e.name },
  el("button", { class: "fm-check", type: "button", "aria-label": `Seleccionar ${e.name}`, tabindex: "-1" }, icon(k)),
  el("span", { class: "fm-name" }, e.name, e.link ? el("span", { class: "muted" }, " ↪") : null),
  el("span", { class: "fm-meta mono" }, e.dir ? "" : fmtBytes(e.size)),
  el("span", { class: "fm-date" }, when(e.mtime)));
  return li;
}

function bars() {
  const n = sel.size;
  $("fm-selbar").hidden = !n;
  $("fm-sel-count").textContent = plural(n, "seleccionado", "seleccionados");
  $("fm-selbar").querySelector('[data-act="rename"]').disabled = n !== 1;
  $("fm-clipbar").hidden = !!n || !clip;
  if (clip) {
    $("fm-clip-text").replaceChildren(`${plural(clip.paths.length, "elemento", "elementos")} para ${clip.op === "cut" ? "mover" : "copiar"}`,
      el("span", { class: "muted" }, clip.from === cur.path ? " · ve a la carpeta de destino" : ""));
    $("fm-paste").disabled = busy;
  }
  $("fm-list").classList.toggle("selecting", n > 0);
}

function select(name, how) {
  const names = items.map((e) => e.name);
  if (how === "only") { sel.clear(); sel.add(name); anchor = name; }
  else if (how === "toggle") { sel.has(name) ? sel.delete(name) : sel.add(name); anchor = name; }
  else if (how === "range" && anchor && names.includes(anchor)) {
    const [a, b] = [names.indexOf(anchor), names.indexOf(name)].sort((x, y) => x - y);
    sel.clear();
    names.slice(a, b + 1).forEach((x) => sel.add(x));
  }
  for (const li of $("fm-list").children) {
    const on = sel.has(li.dataset.name);
    li.classList.toggle("sel", on);
    li.setAttribute("aria-selected", on ? "true" : "false");
  }
  bars();
}

const entry = (name) => cur.items.find((e) => e.name === name);
const selected = () => [...sel].map((n) => join(cur.path, n));

// --- abrir -------------------------------------------------------------------------------------------------
function activate(name) {
  const e = entry(name);
  if (!e) return;
  const p = join(cur.path, e.name);
  if (e.dir) return go(p);
  const k = kind(e);
  if (k === "image" && !/\.(svg|heic|tiff?)$/i.test(e.name)) {
    return sheet(e.name, fmtBytes(e.size), el("div", { class: "fm-preview" }, el("img", { src: url(p, true), alt: e.name })), fileButtons(p));
  }
  if (k === "video" || k === "audio") {
    const media = el(k, { src: url(p, true), controls: true, preload: "metadata", class: "fm-media" });
    return sheet(e.name, fmtBytes(e.size), el("div", { class: "fm-preview" }, media,
      el("p", { class: "muted small" }, "Si no se reproduce, el navegador no conoce ese formato: descárgalo.")), fileButtons(p));
  }
  if (k === "pdf") return window.open(url(p, true), "_blank", "noopener");
  if (k === "text" || (k === "file" && e.size <= 256 * 1024)) return editor(p, e);
  location.href = url(p);
}

function fileButtons(p) {
  return el("div", { class: "btn-row" },
    el("a", { class: "btn btn-sm", href: url(p), download: "" }, "Descargar"),
    el("a", { class: "btn btn-sm", href: url(p, true), target: "_blank", rel: "noopener" }, "Abrir en otra pestaña"));
}

async function editor(p, e) {
  let d;
  try {
    d = await api(`/api/files/text?path=${encodeURIComponent(p)}`);
  } catch (ex) {
    if (/no parece|demasiado grande/.test(ex.message)) { location.href = url(p); return; }
    return toast(ex.message, true);
  }
  let mtime = d.mtime;
  const ta = el("textarea", { class: "fm-text mono", spellcheck: "false", autocapitalize: "off", autocomplete: "off" });
  ta.value = d.content;
  const status = el("span", { class: "muted small" }, "");
  const save = el("button", { class: "btn btn-sm btn-primary", type: "button", disabled: true, onclick: async () => {
    save.disabled = true;
    try {
      mtime = (await api("/api/files/text", { method: "PUT", body: { path: p, content: ta.value, mtime } })).mtime;
      status.textContent = "Guardado";
      original = ta.value;
      open(cur.path, true);
    } catch (ex) {
      toast(ex.message, true);
      save.disabled = false;
    }
  } }, "Guardar");
  let original = d.content;
  ta.addEventListener("input", () => { save.disabled = ta.value === original; status.textContent = save.disabled ? "" : "Sin guardar"; });
  ta.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "s") { ev.preventDefault(); if (!save.disabled) save.click(); }
  });
  sheet(e.name, `${fmtBytes(e.size)} · ${p}`, ta, el("div", { class: "fm-edit-bar" }, status,
    el("a", { class: "btn btn-sm", href: url(p), download: "" }, "Descargar"), save));
  sheetGuard = () => ta.value === original || confirm("Hay cambios sin guardar. ¿Cerrar igualmente?");
  ta.focus();
}

let sheetGuard = null;
function sheet(title, sub, ...body) {
  $("fm-sh-title").textContent = title;
  $("fm-sh-sub").textContent = sub || "";
  $("fm-sh-body").replaceChildren(...body);
  sheetGuard = null;
  $("fm-sheet").hidden = false;
}
function closeSheet(force = false) {
  if ($("fm-sheet").hidden) return;
  if (!force && sheetGuard && !sheetGuard()) return;
  $("fm-sheet").hidden = true;
  $("fm-sh-body").replaceChildren();  // para el vídeo/audio
}

// --- acciones ----------------------------------------------------------------------------------------------
function ask(title, label, value, okText, onok) {
  const input = el("input", { value: value || "", autocomplete: "off", autocapitalize: "off", spellcheck: "false" });
  const err = el("p", { class: "form-error" });
  const form = el("form", { class: "form fm-ask" }, el("label", {}, label, input), err,
    el("button", { class: "btn btn-primary" }, okText));
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    try {
      await onok(input.value.trim());
      closeSheet(true);
    } catch (ex) {
      err.textContent = ex.message;
    }
  };
  sheet(title, cur.path, form);
  input.focus();
  const dot = value?.lastIndexOf(".");
  input.setSelectionRange(0, dot > 0 ? dot : (value || "").length);  // sin la extensión, como en el escritorio
}

function newItem() {
  sheet("Nuevo", cur.path, el("div", { class: "btn-row fm-new" },
    el("button", { class: "btn", type: "button", onclick: () => ask("Nueva carpeta", "Nombre", "", "Crear", async (name) => {
      await api("/api/files/new", { method: "POST", body: { path: cur.path, name, dir: true } });
      await open(cur.path);
      select(name, "only");
    }) }, "Carpeta"),
    el("button", { class: "btn", type: "button", onclick: () => ask("Nuevo archivo de texto", "Nombre", "nuevo.txt", "Crear", async (name) => {
      await api("/api/files/new", { method: "POST", body: { path: cur.path, name, dir: false } });
      await open(cur.path);
      activate(name);
    }) }, "Archivo de texto"),
    el("button", { class: "btn", type: "button", onclick: () => { closeSheet(true); $("fm-upload").click(); } }, "Subir archivos")));
}

function rename() {
  if (sel.size !== 1) return;
  const [name] = sel;
  ask("Renombrar", "Nuevo nombre", name, "Renombrar", async (to) => {
    if (to === name) return;
    await api("/api/files/rename", { method: "POST", body: { path: join(cur.path, name), name: to } });
    await open(cur.path);
    select(to, "only");
  });
}

function toClip(op) {
  if (!sel.size) return;
  clip = { op, paths: selected(), from: cur.path };
  store(CLIP_KEY, clip);
  sel.clear();
  render();
}

async function paste() {
  if (!clip || busy) return;
  const move = clip.op === "cut";
  try {
    const j = await api("/api/files/paste", { method: "POST", body: { sources: clip.paths, dest: cur.path, move } });
    if (move) { clip = null; store(CLIP_KEY, null); }
    follow(j, move ? "Moviendo" : "Copiando");
  } catch (e) {
    toast(e.message, true);
  }
}

async function remove() {
  if (!sel.size) return;
  const names = [...sel];
  const what = names.length === 1 ? `«${names[0]}»` : plural(names.length, "elemento", "elementos");
  const dirs = names.filter((n) => entry(n)?.dir).length;
  if (!confirm(`¿Borrar ${what}${dirs ? " (las carpetas, con todo lo que tienen dentro)" : ""}? No hay papelera: no se puede deshacer.`)) return;
  try {
    follow(await api("/api/files/delete", { method: "POST", body: { paths: selected() } }), "Borrando");
  } catch (e) {
    toast(e.message, true);
  }
}

function download() {
  for (const p of selected()) {
    const a = el("a", { href: url(p), download: "" });
    document.body.append(a);
    a.click();
    a.remove();
  }
}

/** Sigue una tarea del servidor en la barra de progreso; al acabar, recarga. */
function follow({ job, title }, verb) {
  busy = true;
  bars();
  const jobUrl = `/api/files/jobs/${job}`;
  progress(`${verb}…`, null, () => watchJob(jobUrl, title, { ok: ["Hecho", true], failed: ["Ha fallado", false] }));
  const poll = async () => {
    let j;
    try {
      j = await api(jobUrl);
    } catch (e) {
      if (e.message === "no autenticado") return;
      return setTimeout(poll, 2000);
    }
    if (j.status === "running") {
      const last = j.lines.at(-1)?.replace(/^\S+\s+/, "") || "";
      progress(`${verb}… ${last}`, null, () => watchJob(jobUrl, title, { ok: ["Hecho", true], failed: ["Ha fallado", false] }));
      return setTimeout(poll, 1000);
    }
    busy = false;
    progress(null);
    if (j.status === "failed") toast(j.lines.at(-1)?.replace(/^\S+\s+/, "") || "Ha fallado", true);
    else toast({ Copiando: "Copiado", Moviendo: "Movido", Borrando: "Borrado" }[verb] || "Hecho");
    sel.clear();
    open(cur.path, true);
  };
  setTimeout(poll, 400);
}

function progress(text, pct = null, onlog = null) {
  const box = $("fm-progress");
  box.hidden = !text;
  if (!text) return;
  $("fm-progress-text").textContent = text;
  box.classList.toggle("indet", pct == null);
  $("fm-progress-bar").style.width = pct == null ? "" : `${pct}%`;
  $("fm-progress-log").hidden = !onlog;
  $("fm-progress-log").onclick = onlog;
}

// --- subir -------------------------------------------------------------------------------------------------
function put(dir, file, onprogress) {
  return new Promise((ok, bad) => {
    const x = new XMLHttpRequest();
    x.open("PUT", `/api/files/upload?path=${encodeURIComponent(dir)}&name=${encodeURIComponent(file.name)}`);
    x.upload.onprogress = (ev) => ev.lengthComputable && onprogress(ev.loaded / ev.total);
    x.onload = () => {
      let d = {};
      try { d = JSON.parse(x.responseText); } catch { /* vacío */ }
      x.status < 300 ? ok(d) : bad(new Error(d.detail || `error ${x.status}`));
    };
    x.onerror = () => bad(new Error("se cortó la conexión"));
    x.send(file);
  });
}

async function upload(files) {
  files = [...files].filter((f) => f.size || f.type);  // las carpetas arrastradas llegan como archivos vacíos sin tipo
  if (!files.length || busy) return;
  busy = true;
  bars();
  const dir = cur.path, total = files.reduce((a, f) => a + f.size, 0) || 1;
  let done = 0, ok = 0;
  for (const [i, f] of files.entries()) {
    try {
      await put(dir, f, (r) => progress(`Subiendo ${f.name} (${i + 1}/${files.length})`, ((done + f.size * r) / total) * 100));
      ok++;
    } catch (e) {
      toast(`${f.name}: ${e.message}`, true);
    }
    done += f.size;
  }
  busy = false;
  progress(null);
  if (ok) toast(`${plural(ok, "archivo subido", "archivos subidos")}`);
  if (cur.path === dir) open(dir, true);
  bars();
}

// --- eventos -----------------------------------------------------------------------------------------------
function wireList() {
  const list = $("fm-list");
  let press = null, pressed = false, byMouse = false;
  const nameOf = (ev) => ev.target.closest(".fm-row")?.dataset.name;

  list.addEventListener("click", (ev) => {
    const name = nameOf(ev);
    if (name == null) return;
    if (pressed) { pressed = false; return; }  // acaba de seleccionarse con una pulsación larga
    byMouse = mouse(ev);
    if (ev.target.closest(".fm-check")) return select(name, "toggle");
    if (byMouse) {
      if (ev.shiftKey) return select(name, "range");
      if (ev.ctrlKey || ev.metaKey) return select(name, "toggle");
      return select(name, "only");
    }
    if (sel.size) return select(name, "toggle");
    activate(name);
  });
  list.addEventListener("dblclick", (ev) => {
    const name = nameOf(ev);
    if (name != null && byMouse && !ev.target.closest(".fm-check")) activate(name);  // con el dedo ya abre el clic
  });
  // pulsación larga = seleccionar (en el móvil)
  list.addEventListener("pointerdown", (ev) => {
    if (ev.pointerType === "mouse") return;
    const name = nameOf(ev);
    if (name == null) return;
    pressed = false;
    press = setTimeout(() => {
      pressed = true;
      navigator.vibrate?.(15);
      select(name, sel.has(name) ? "toggle" : sel.size ? "toggle" : "only");
    }, 450);
  });
  for (const t of ["pointerup", "pointercancel", "pointermove"]) {
    list.addEventListener(t, (ev) => { if (t !== "pointermove" || Math.abs(ev.movementY) > 4) clearTimeout(press); });
  }
  list.addEventListener("contextmenu", (ev) => { if (!fine.matches && nameOf(ev) != null) ev.preventDefault(); });
  // clic en el hueco: quitar la selección
  $("fm-wrap").addEventListener("click", (ev) => { if (ev.target.id === "fm-wrap" || ev.target.id === "fm-list") select(null, "none"); });
}

function wireDrop() {
  const view = $("view-files"), drop = $("fm-drop");
  let depth = 0;
  const isFiles = (ev) => [...(ev.dataTransfer?.types || [])].includes("Files");
  view.addEventListener("dragenter", (ev) => { if (!isFiles(ev)) return; ev.preventDefault(); depth++; drop.hidden = false; });
  view.addEventListener("dragover", (ev) => { if (isFiles(ev)) ev.preventDefault(); });
  view.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; drop.hidden = true; } });
  view.addEventListener("drop", (ev) => {
    if (!isFiles(ev)) return;
    ev.preventDefault();
    depth = 0;
    drop.hidden = true;
    upload(ev.dataTransfer.files);
  });
}

function onKey(ev) {
  if ($("view-files").hidden) return;
  if (!$("fm-sheet").hidden) { if (ev.key === "Escape") closeSheet(); return; }
  const t = ev.target instanceof Element ? ev.target : document.body;
  const typing = t.matches("input, textarea, select");
  const mod = ev.ctrlKey || ev.metaKey;
  if (typing) { if (ev.key === "Escape") t.blur(); return; }
  if (ev.key === "Enter" && t.closest("button, a")) return;  // que haga lo suyo el botón
  const k = ev.key.toLowerCase();
  if (mod && k === "a") { ev.preventDefault(); items.forEach((e) => sel.add(e.name)); select(null, "none"); }
  else if (mod && k === "c") toClip("copy");
  else if (mod && k === "x") toClip("cut");
  else if (mod && k === "v") paste();
  else if (ev.key === "Delete") remove();
  else if (ev.key === "F2") rename();
  else if (ev.key === "Enter" && sel.size === 1) activate([...sel][0]);
  else if (ev.key === "Backspace" && cur?.parent) go(cur.parent);
  else if (ev.key === "Escape") { sel.clear(); select(null, "none"); }
  else if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
    ev.preventDefault();
    const names = items.map((e) => e.name);
    const i = names.indexOf(anchor);
    const n = names[Math.max(0, Math.min(names.length - 1, i < 0 ? 0 : i + (ev.key === "ArrowDown" ? 1 : -1)))];
    if (n == null) return;
    select(n, ev.shiftKey ? "toggle" : "only");
    $("fm-list").querySelector(`[data-name="${CSS.escape(n)}"]`)?.scrollIntoView({ block: "nearest" });
  }
}

export function init() {
  wireList();
  wireDrop();
  $("fm-show-hidden").checked = showHidden;
  $("fm-show-hidden").onchange = (ev) => { showHidden = ev.target.checked; store(HIDDEN_KEY, showHidden); render(); };
  $("fm-filter").oninput = () => cur && render();
  $("fm-root").onchange = (ev) => go(ev.target.value);
  $("fm-up").onclick = () => cur?.parent && go(cur.parent);
  $("fm-new").onclick = () => cur && newItem();
  $("fm-upload-btn").onclick = () => $("fm-upload").click();
  $("fm-upload").onchange = (ev) => { upload(ev.target.files); ev.target.value = ""; };
  $("fm-sel-clear").onclick = () => { sel.clear(); select(null, "none"); };
  $("fm-clip-clear").onclick = () => { clip = null; store(CLIP_KEY, null); render(); };
  $("fm-paste").onclick = paste;
  const acts = { copy: () => toClip("copy"), cut: () => toClip("cut"), rename, download, delete: remove };
  for (const b of $("fm-selbar").querySelectorAll("[data-act]")) b.onclick = acts[b.dataset.act];
  $("fm-sh-close").onclick = () => closeSheet();
  $("fm-sheet").addEventListener("click", (ev) => { if (ev.target.id === "fm-sheet") closeSheet(); });
  document.addEventListener("keydown", onKey);
}

export function show(args = []) {
  const path = args[0] ? decodeURIComponent(args.join("/")) : null;
  if (path && path === cur?.path) return;  // volver a la pestaña: tal cual estaba
  open(path || cur?.path);
}

export function hide() {
  closeSheet(true);
}
