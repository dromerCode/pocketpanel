// Terminal: varias sesiones a la vez, cada una en su pestaña con su xterm y su WebSocket (y su canal SSH en el
// host). Las de fondo siguen vivas; al cerrar una pestaña se cierra su shell.
import { el, toast, wsUrl } from "/js/api.js";

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

const sessions = [];  // { id, mode, sid, term, fit, box, ws, title, alive }
let active = null;
let seq = 0;
let ctrl = false;

function send(s, data) {
  if (s?.ws?.readyState === WebSocket.OPEN) s.ws.send(enc.encode(data));
}

function refit(s = active) {
  if (!s || $("view-terminal").hidden || !s.box.clientHeight) return;
  s.fit.fit();
  if (s.ws?.readyState === WebSocket.OPEN) s.ws.send(JSON.stringify({ resize: [s.term.cols, s.term.rows] }));
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

function renderTabs() {
  $("term-tabs").replaceChildren(...sessions.map((s) => el("div", {
    class: `term-tab${s === active ? " on" : ""}${s.alive ? "" : " dead"}`, role: "tab",
    "aria-selected": String(s === active), title: s.alive ? label(s) : `${label(s)} (cerrada)`,
    onclick: () => select(s),
  }, el("span", { class: "term-tab-name" }, label(s)),
  el("button", { type: "button", class: "term-tab-x", title: "Cerrar", "aria-label": `Cerrar ${label(s)}`,
    onclick: (e) => { e.stopPropagation(); close(s); } }, "×"))));
  $("term-new").disabled = sessions.length >= MAX;
}

function select(s) {
  active = s;
  for (const x of sessions) x.box.hidden = x !== s;
  renderTabs();
  requestAnimationFrame(() => { refit(s); s.term.focus(); });
  $("term-tabs").querySelector(".term-tab.on")?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function connect(s) {
  if (s.ws) { s.ws.onclose = null; s.ws.close(); }
  s.term.reset();
  refit(s);
  const q = new URLSearchParams({ mode: s.mode, cols: s.term.cols, rows: s.term.rows });
  if (s.sid) q.set("session", s.sid);
  const ws = s.ws = new WebSocket(wsUrl(`/ws/term?${q}`));
  ws.binaryType = "arraybuffer";
  ws.onmessage = (e) => {
    if (typeof e.data === "string") {
      try { s.term.write(`\r\n\x1b[31m${JSON.parse(e.data).error}\x1b[0m\r\n`); } catch { /* nada */ }
    } else s.term.write(new Uint8Array(e.data));
  };
  ws.onopen = () => { s.alive = true; renderTabs(); refit(s); if (s === active) s.term.focus(); };
  ws.onclose = (e) => {
    if (e.code === 4401) return location.reload();
    s.alive = false;
    renderTabs();
    s.term.write("\r\n\x1b[2m[sesión cerrada · toca ↻ para reconectar]\x1b[0m\r\n");
  };
}

/** Una sesión nueva en su pestaña. tmux y las de Claude no se repiten: si ya hay una, se va a esa. */
export function open(mode = "shell", sid = null) {
  const same = mode !== "shell" && sessions.find((s) => s.mode === mode && s.sid === sid);
  if (same) {
    select(same);
    if (!same.alive) connect(same);
    return;
  }
  if (sessions.length >= MAX) return toast(`Como mucho ${MAX} sesiones a la vez: cierra alguna`, true);
  const box = el("div", { class: "term-pane" });
  $("term").append(box);
  const term = new Terminal(OPTS);
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(box);
  const s = { id: ++seq, mode, sid, term, fit, box, ws: null, title: "", alive: false };
  term.onData((d) => {
    if (ctrl && d.length === 1) {
      const c = d.toUpperCase().charCodeAt(0);
      if (c >= 64 && c <= 95) d = String.fromCharCode(c - 64);
      setCtrl(false);
    }
    send(s, d);
  });
  // bash pone de título «usuario@host: carpeta»: la pestaña enseña la carpeta
  term.onTitleChange((t) => { s.title = t.includes(": ") ? t.slice(t.indexOf(": ") + 2) : t; renderTabs(); });
  sessions.push(s);
  select(s);
  connect(s);
}

function close(s) {
  if (s.ws) { s.ws.onclose = null; s.ws.close(); }
  s.term.dispose();
  s.box.remove();
  const i = sessions.indexOf(s);
  sessions.splice(i, 1);
  if (!sessions.length) return open();  // siempre queda una
  if (s === active) select(sessions[Math.min(i, sessions.length - 1)]);
  else renderTabs();
}

export function init() {
  new ResizeObserver(() => refit()).observe($("term"));
  $("term-new").onclick = () => open();
  $("term-tmux").onclick = () => open("tmux");
  $("term-reconnect").onclick = () => active && connect(active);
  for (const b of document.querySelectorAll("#term-keys button")) {
    // pointerdown + preventDefault: no robar el foco (el teclado del móvil sigue abierto)
    b.addEventListener("pointerdown", (e) => e.preventDefault());
    b.addEventListener("click", () => {
      const k = b.dataset.k;
      if (k === "ctrl") return setCtrl(!ctrl);
      send(active, KEYS[k] ?? k);
      if (ctrl) setCtrl(false);
      active?.term.focus();
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
  requestAnimationFrame(() => refit());
}
