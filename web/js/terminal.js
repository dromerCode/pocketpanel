import { wsUrl } from "./api.js";

let term, fit, ws;
let mode = "shell";
let session = null;
let ctrl = false;
const enc = new TextEncoder();
const $ = (id) => document.getElementById(id);

const KEYS = {
  esc: "\x1b", tab: "\t", up: "\x1b[A", down: "\x1b[B", right: "\x1b[C", left: "\x1b[D",
};

function send(data) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(enc.encode(data));
}

function sendResize() {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ resize: [term.cols, term.rows] }));
}

function refit() {
  if ($("view-terminal").hidden || !$("term").clientHeight) return;
  fit.fit();
  sendResize();
}

function setCtrl(on) {
  ctrl = on;
  document.querySelector('#term-keys [data-k="ctrl"]').classList.toggle("on", on);
}

function updateHeader() {
  for (const b of document.querySelectorAll("#view-terminal .seg-btn")) b.classList.toggle("active", b.dataset.mode === mode);
  $("term-label").textContent = mode === "resume" ? `claude ${session.slice(0, 8)}` : "";
}

export function connect(m, sid = null) {
  mode = m;
  session = sid;
  updateHeader();
  if (ws) { ws.onclose = null; ws.close(); }
  term.reset();
  refit();
  const q = new URLSearchParams({ mode, cols: term.cols, rows: term.rows });
  if (sid) q.set("session", sid);
  ws = new WebSocket(wsUrl(`/ws/term?${q}`));
  ws.binaryType = "arraybuffer";
  ws.onmessage = (e) => {
    if (typeof e.data === "string") {
      try { term.write(`\r\n\x1b[31m${JSON.parse(e.data).error}\x1b[0m\r\n`); } catch { /* nada */ }
    } else term.write(new Uint8Array(e.data));
  };
  ws.onopen = () => { refit(); term.focus(); };
  ws.onclose = (e) => {
    if (e.code === 4401) return location.reload();
    term.write("\r\n\x1b[2m[sesión cerrada · toca ↻ para reconectar]\x1b[0m\r\n");
  };
}

export function init() {
  term = new Terminal({
    fontFamily: 'ui-monospace, "JetBrains Mono", Menlo, monospace',
    fontSize: 13,
    cursorBlink: true,
    scrollback: 5000,
    theme: { background: "#0a0b0c", foreground: "#ebe9e4", cursor: "#a6e36e", selectionBackground: "#3a4a2c" },
  });
  fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open($("term"));
  term.onData((d) => {
    if (ctrl && d.length === 1) {
      const c = d.toUpperCase().charCodeAt(0);
      if (c >= 64 && c <= 95) d = String.fromCharCode(c - 64);
      setCtrl(false);
    }
    send(d);
  });
  new ResizeObserver(() => refit()).observe($("term"));

  for (const b of document.querySelectorAll("#view-terminal .seg-btn")) b.onclick = () => connect(b.dataset.mode);
  $("term-reconnect").onclick = () => connect(mode, session);
  for (const b of document.querySelectorAll("#term-keys button")) {
    // pointerdown + preventDefault: no robar el foco (el teclado del móvil sigue abierto)
    b.addEventListener("pointerdown", (e) => e.preventDefault());
    b.addEventListener("click", () => {
      const k = b.dataset.k;
      if (k === "ctrl") return setCtrl(!ctrl);
      send(KEYS[k] ?? k);
      if (ctrl) setCtrl(false);
      term.focus();
    });
  }
}

export function show(args = []) {
  if (args[0] === "resume" && args[1]) {
    history.replaceState(null, "", "#terminal");
    connect("resume", args[1]);
    return;
  }
  if (!ws) connect(mode);
  requestAnimationFrame(refit);
}
