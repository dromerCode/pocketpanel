// Terminal: varias sesiones a la vez, cada una en su pestaña con su xterm y su WebSocket (y su canal SSH en el
// host). Se pueden ver varias juntas (dividir); las que no se ven siguen vivas y al cerrar una pestaña se cierra su
// shell.
//
// Copiar y pegar: por http://IP:puerto el navegador no da la API del portapapeles, y en el móvil xterm no deja
// seleccionar con el dedo. Con ratón: seleccionar y Ctrl+C (sin selección sigue siendo ^C), Ctrl+Mayús+C/V o el
// botón derecho; en tmux con ratón, seleccionar con Mayús pulsada. En el móvil, «Copiar» abre el texto de la sesión
// en un elemento normal, donde se selecciona como en cualquier web, y «Pegar» da un sitio donde pegar.
import { copyText, el, toast, wsUrl } from "/js/api.js";

// El servidor SSH deja 10 canales por conexión (MaxSessions) y el panel también usa algunos para lo suyo
const MAX = 6;
const OPTS = {
  fontFamily: 'ui-monospace, "JetBrains Mono", Menlo, monospace',
  fontSize: 13,
  cursorBlink: true,
  scrollback: 5000,
  theme: { background: "#0a0b0c", foreground: "#ebe9e4", cursor: "#a6e36e", selectionBackground: "#3a4a2c" },
};
const KEYS = {
  esc: "\x1b", tab: "\t", up: "\x1b[A", down: "\x1b[B", right: "\x1b[C", left: "\x1b[D",
};
const enc = new TextEncoder();
const $ = (id) => document.getElementById(id);

const sessions = [];  // { id, mode, sid, term, fit, box, host, ws, title, alive, size, over }
let panes = [];       // las que se ven, en orden; una sola = sin dividir
let active = null;    // de las que se ven, la que recibe el teclado
let seq = 0;
let ctrl = false;

// Con el móvil en vertical no caben más de dos
const maxPanes = () => ($("term").clientWidth >= 700 ? 4 : 2);

function send(s, data) {
  if (s?.ws?.readyState === WebSocket.OPEN) s.ws.send(enc.encode(data));
}

function refit(s) {
  if (!s || $("view-terminal").hidden || !s.host.clientHeight) return;
  s.fit.fit();
  const size = `${s.term.cols}x${s.term.rows}`;
  if (size !== s.size && s.ws?.readyState === WebSocket.OPEN) {
    s.size = size;
    s.ws.send(JSON.stringify({ resize: [s.term.cols, s.term.rows] }));
  }
}

const refitAll = () => panes.forEach(refit);

/** Suelta su WebSocket sin el aviso de «sesión cerrada» (se reconecta o se cierra la pestaña). */
function hangUp(s) {
  if (!s.ws) return;
  s.ws.onclose = null;
  s.ws.close();
  s.ws = null;
}

function setCtrl(on) {
  ctrl = on;
  document.querySelector('#term-keys [data-k="ctrl"]').classList.toggle("on", on);
}

function label(s) {
  if (s.mode === "tmux") return "tmux claude";
  if (s.mode === "resume") return `claude ${s.sid.slice(0, 8)}`;
  return `${sessions.indexOf(s) + 1} · ${s.title || "shell"}`;
}

function buttons() {
  $("term-new").disabled = sessions.length >= MAX;
  $("term-split").disabled = panes.length >= maxPanes() || (sessions.length >= MAX && panes.length >= sessions.length);
  $("term-join").hidden = panes.length < 2;
}

function renderTabs() {
  $("term-tabs").replaceChildren(...sessions.map((s) => el("div", {
    class: `term-tab${s === active ? " on" : panes.includes(s) ? " vis" : ""}${s.alive ? "" : " dead"}`, role: "tab",
    "aria-selected": String(s === active), title: s.alive ? label(s) : `${label(s)} (cerrada)`,
    onclick: () => select(s),
  }, el("span", { class: "term-tab-name" }, label(s)),
  el("button", { type: "button", class: "term-tab-x", title: "Cerrar", "aria-label": `Cerrar ${label(s)}`,
    onclick: (e) => { e.stopPropagation(); close(s); } }, "×"))));
  buttons();
  $("term-tabs").querySelector(".term-tab.on")?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

/** Coloca las que se ven: dos, lado a lado si hay más ancho que alto (si no, una encima de otra); tres o cuatro, en
 *  cuadrícula de dos columnas (con tres, la última ocupa toda la fila). */
function arrange() {
  const box = $("term");
  if (!box.clientWidth) return;  // vista oculta: ya se colocará al volver
  if (panes.length > maxPanes()) panes = [active, ...panes.filter((x) => x !== active)].slice(0, maxPanes());
  const n = panes.length;
  const cols = n === 2 ? (box.clientWidth > box.clientHeight ? 2 : 1) : Math.min(n, 2);
  box.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
  box.classList.toggle("split", n > 1);
  for (const s of sessions) {
    const i = panes.indexOf(s);
    s.box.hidden = i < 0;
    s.box.style.order = i;
    s.box.style.gridColumn = n === 3 && i === 2 ? "1 / -1" : "";
    s.box.classList.toggle("focus", s === active);
  }
}

function layout(focus = true) {
  arrange();
  renderTabs();
  requestAnimationFrame(() => {
    refitAll();
    if (focus && active && !active.over) active.term.focus();
  });
}

/** El foco pasa a otra de las que se ven (al tocarla). */
function focusPane(s) {
  if (s === active || !panes.includes(s)) return;
  active = s;
  arrange();
  renderTabs();
}

/** Desde su pestaña: si no se ve, ocupa el sitio de la que tenía el foco. */
function select(s) {
  if (!panes.includes(s)) {
    const i = panes.indexOf(active);
    if (i >= 0) panes[i] = s;
    else panes.push(s);
  }
  active = s;
  layout();
}

/** Otra más a la vista, justo después de la que tiene el foco, y el foco pasa a ella. */
function addPane(s) {
  panes.splice(panes.indexOf(active) + 1, 0, s);
  active = s;
  layout();
}

function connect(s) {
  hangUp(s);
  s.term.reset();
  refit(s);
  s.size = `${s.term.cols}x${s.term.rows}`;  // va en la URL
  const q = new URLSearchParams({ mode: s.mode, cols: s.term.cols, rows: s.term.rows });
  if (s.sid) q.set("session", s.sid);
  const ws = s.ws = new WebSocket(wsUrl(`/ws/term?${q}`));
  ws.binaryType = "arraybuffer";
  ws.onmessage = (e) => {
    if (typeof e.data === "string") {
      try { s.term.write(`\r\n\x1b[31m${JSON.parse(e.data).error}\x1b[0m\r\n`); } catch { /* nada */ }
    } else s.term.write(new Uint8Array(e.data));
  };
  ws.onopen = () => { s.alive = true; renderTabs(); refit(s); if (s === active && !s.over) s.term.focus(); };
  ws.onclose = (e) => {
    if (e.code === 4401) return location.reload();
    s.alive = false;
    renderTabs();
    s.term.write("\r\n\x1b[2m[sesión cerrada · toca ↻ para reconectar]\x1b[0m\r\n");
  };
}

async function copyOut(text) {
  if (!text) return toast("No hay nada seleccionado", true);
  const ok = await copyText(text);
  toast(ok ? "Copiado" : "No se ha podido copiar: mantén pulsado el texto y elige Copiar", !ok);
}

/** Ctrl+C con algo seleccionado copia (sin selección sigue siendo ^C); Ctrl+Mayús+C copia siempre (en vez de abrir
 *  las herramientas del navegador); Ctrl+Mayús+V se la deja al navegador, que pega en la terminal. */
function keys(s, e) {
  if (e.type !== "keydown" || !e.ctrlKey || e.altKey || e.metaKey) return true;
  const k = e.key.toLowerCase();
  if (k === "c" && (e.shiftKey || s.term.hasSelection())) {
    e.preventDefault();
    copyOut(s.term.getSelection());
    if (!e.shiftKey) s.term.clearSelection();
    return false;
  }
  return !(k === "v" && e.shiftKey);
}

/** Una sesión nueva en su pestaña. tmux y las de Claude no se repiten: si ya hay una, se va a esa.
 *  Con split, en un hueco nuevo junto a las que se ven; si no, en el de la que tiene el foco. */
export function open(mode = "shell", sid = null, split = false) {
  const same = mode !== "shell" && sessions.find((s) => s.mode === mode && s.sid === sid);
  if (same) {
    select(same);
    if (!same.alive) connect(same);
    return;
  }
  if (sessions.length >= MAX) return toast(`Como mucho ${MAX} sesiones a la vez: cierra alguna`, true);
  const host = el("div", { class: "term-host" });
  const box = el("div", { class: "term-pane" }, host);
  $("term").append(box);
  const term = new Terminal(OPTS);
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(host);
  const s = { id: ++seq, mode, sid, term, fit, box, host, ws: null, title: "", alive: false, size: "", over: null };
  term.onData((d) => {
    if (ctrl && d.length === 1) {
      const c = d.toUpperCase().charCodeAt(0);
      if (c >= 64 && c <= 95) d = String.fromCharCode(c - 64);
      setCtrl(false);
    }
    send(s, d);
  });
  term.attachCustomKeyEventHandler((e) => keys(s, e));
  // bash pone de título «usuario@host: carpeta»: la pestaña enseña la carpeta
  term.onTitleChange((t) => { s.title = t.includes(": ") ? t.slice(t.indexOf(": ") + 2) : t; renderTabs(); });
  box.addEventListener("pointerdown", () => focusPane(s));
  box.addEventListener("focusin", () => focusPane(s));
  sessions.push(s);
  if (split && panes.length) addPane(s);
  else select(s);
  connect(s);
}

function split() {
  if (panes.length >= maxPanes()) return;
  if (sessions.length < MAX) return open("shell", null, true);
  // sin sitio para otra sesión: se enseña una de las que ya hay
  const idle = sessions.find((s) => !panes.includes(s));
  if (idle) addPane(idle);
}

function close(s) {
  closeOver(s, false);
  hangUp(s);
  s.term.dispose();
  s.box.remove();
  const i = sessions.indexOf(s);
  sessions.splice(i, 1);
  if (!sessions.length) {
    panes = [];
    active = null;
    return open();  // siempre queda una
  }
  const at = panes.indexOf(s);
  if (at >= 0) {
    panes.splice(at, 1);
    if (!panes.length) panes = [sessions[Math.min(i, sessions.length - 1)]];
    if (s === active) active = panes[Math.min(at, panes.length - 1)];
    layout();
  } else renderTabs();
}

// ---- copiar y pegar en el móvil ----

/** Todo el texto de la sesión (lo que se ve y lo que ha subido), con las líneas que xterm partió vueltas a unir. */
function bufferText(term) {
  const b = term.buffer.active;
  const out = [];
  for (let i = 0; i < b.length; i++) {
    const line = b.getLine(i);
    if (!line) continue;
    const t = line.translateToString(!b.getLine(i + 1)?.isWrapped);  // sin recortar si sigue en la siguiente
    if (line.isWrapped && out.length) out[out.length - 1] += t;
    else out.push(t);
  }
  while (out.length && !out[out.length - 1]) out.pop();
  return out.join("\n");
}

function closeOver(s, focus = true) {
  if (!s?.over) return;
  s.over.remove();
  s.over = null;
  document.removeEventListener("selectionchange", s.onSel);
  if (focus) s.term.focus();
}

function overlay(s, hint, body, ...buttons) {
  closeOver(s, false);
  s.over = el("div", { class: "term-over" },
    el("div", { class: "term-over-bar" }, el("span", { class: "muted" }, hint), ...buttons,
      el("button", { type: "button", class: "btn btn-sm", onclick: () => closeOver(s) }, "Listo")),
    body);
  s.over.addEventListener("keydown", (e) => { if (e.key === "Escape") closeOver(s); });
  s.box.append(s.over);
}

function showCopy(s) {
  const text = bufferText(s.term);
  const pre = el("pre", { tabindex: "-1" }, text || " ");
  const btn = el("button", { type: "button", class: "btn btn-sm btn-primary" }, "Copiar todo");
  const picked = () => {
    const sel = document.getSelection();
    return sel && !sel.isCollapsed && pre.contains(sel.anchorNode) ? sel.toString() : "";
  };
  btn.onclick = async () => {
    const t = picked() || text;
    await copyOut(t);
    closeOver(s);
  };
  s.term.blur();
  overlay(s, "Mantén pulsado para seleccionar", pre, btn);  // cierra la que hubiera, con su s.onSel
  s.onSel = () => { btn.textContent = picked() ? "Copiar selección" : "Copiar todo"; };
  document.addEventListener("selectionchange", s.onSel);
  // Al mismo sitio que se estaba viendo (abajo del todo, o donde se hubiera subido)
  const b = s.term.buffer.active;
  pre.scrollTop = b.viewportY >= b.baseY ? pre.scrollHeight : pre.scrollHeight * (b.viewportY / Math.max(1, b.length));
}

function showPaste(s) {
  const ta = el("textarea", { placeholder: "Mantén pulsado aquí y elige Pegar", autocapitalize: "off",
    autocomplete: "off", spellcheck: "false" });
  const go = () => {
    if (ta.value) s.term.paste(ta.value);  // xterm lo manda como pegado (bracketed paste si el programa lo pide)
    closeOver(s);
  };
  const btn = el("button", { type: "button", class: "btn btn-sm btn-primary", onclick: go }, "Enviar");
  overlay(s, "Lo que pegues va a la terminal", ta, btn);
  ta.focus();
}

async function paste(s) {
  // Con HTTPS hay API (el navegador pregunta la primera vez); por http://IP no, y se pega a mano
  try {
    const t = await navigator.clipboard.readText();
    if (t) return s.term.paste(t);
  } catch { /* sin API o sin permiso */ }
  showPaste(s);
}

export function init() {
  // al estrecharse (el móvil a vertical) pueden sobrar paneles: layout también repinta las pestañas
  new ResizeObserver(() => layout(false)).observe($("term"));
  $("term-new").onclick = () => open();
  $("term-split").onclick = split;
  $("term-join").onclick = () => { panes = [active]; layout(); };
  $("term-tmux").onclick = () => open("tmux");
  $("term-reconnect").onclick = () => active && connect(active);
  for (const b of document.querySelectorAll("#term-keys button")) {
    // pointerdown + preventDefault: no robar el foco (el teclado del móvil sigue abierto)
    b.addEventListener("pointerdown", (e) => e.preventDefault());
    b.addEventListener("click", () => {
      if (!active) return;
      if (b.dataset.act === "copy") return showCopy(active);
      if (b.dataset.act === "paste") return paste(active);
      closeOver(active, false);
      const k = b.dataset.k;
      if (k === "ctrl") return setCtrl(!ctrl);
      send(active, KEYS[k] ?? k);
      if (ctrl) setCtrl(false);
      active.term.focus();
    });
  }
}

export function show(args = []) {
  if (args[0] === "resume" && args[1]) {
    history.replaceState(null, "", "#terminal");
    open("resume", args[1]);
    return;
  }
  if (!sessions.length) open();
  else layout(false);
}
