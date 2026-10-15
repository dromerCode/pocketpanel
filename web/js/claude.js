import { api, el, fmtAgo, panel, toast, wsUrl } from "./api.js";

const $ = (id) => document.getElementById(id);
let ws = null;
let sessions = [];
let lastReport = null;
let running = false;      // hay un turno en marcha (en cualquier conversación)
let runningSid = null;
let inChat = false;
let sid = null;           // conversación abierta (null = nueva sin id todavía)
let pendingNew = false;   // hemos mandado el primer mensaje de una conversación nueva
let syncing = false;      // esperando el "state" tras attach: ignorar eventos sueltos
let seen = { turn: null, n: -1 };
let curText = null;       // burbuja de texto de Claude en curso
let tools = {};
let working = null;
let files = [];            // adjuntos pendientes de enviar
const ATTACH_RE = /\n*\[Archivos adjuntos para Claude:\n([\s\S]*?)\]\s*$/;

DOMPurify.addHook("afterSanitizeAttributes", (n) => {
  if (n.tagName === "A") { n.setAttribute("target", "_blank"); n.setAttribute("rel", "noopener"); }
});

/* ---------- WebSocket ---------- */

function connectWs() {
  ws = new WebSocket(wsUrl("/ws/claude"));
  ws.onopen = () => {
    wsSend({ visible: !document.hidden });
    if (inChat && sid) openChat(sid, $("cl-title").textContent);
    else attach(null);
  };
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = (e) => {
    if (e.code === 4401) return location.reload();
    setTimeout(connectWs, 2000);
  };
}

function wsSend(obj) {
  if (ws?.readyState !== WebSocket.OPEN) { toast("Sin conexión con el servidor, reintentando…", true); return false; }
  ws.send(JSON.stringify(obj));
  return true;
}

function attach(id) {
  syncing = true;
  seen = { turn: null, n: -1 };
  wsSend({ attach: id });
}

function handle(ev) {
  if (ev.t === "state") {
    running = ev.running;
    runningSid = ev.session;
    syncing = false;
    updateRunningUi();
    return;
  }
  if (ev.t === "user") { running = true; runningSid = ev.sid; }
  if (ev.t === "session") runningSid = ev.id;
  if (ev.t === "idle") {
    running = false;
    updateRunningUi();
    loadSessions();  // en pantalla ancha la lista está siempre a la vista
    return;
  }
  if (!inChat || syncing) { updateRunningUi(); return; }

  if (ev.t === "session" && pendingNew) {
    sid = ev.id;
    pendingNew = false;
    loadSessions();
  }
  const mine = ev.sid === sid || (pendingNew && ev.sid == null) || (ev.t === "session" && ev.id === sid);
  if (!mine) return;
  if (ev.n != null) {
    if (ev.turn === seen.turn && ev.n <= seen.n) return;
    seen = { turn: ev.turn, n: ev.n };
  }
  render(ev);
  updateRunningUi();
}

/* ---------- Pintado de mensajes ---------- */

function nearBottom() {
  const m = $("cl-msgs");
  return m.scrollHeight - m.scrollTop - m.clientHeight < 120;
}

function scrollDown(force) {
  const m = $("cl-msgs");
  if (force || nearBottom()) m.scrollTop = m.scrollHeight;
}

function markdown(target, raw) {
  target.innerHTML = DOMPurify.sanitize(marked.parse(raw));
}

let mdQueued = false;
function flushText() {
  mdQueued = false;
  if (!curText) return;
  const stick = nearBottom();
  markdown(curText.el, curText.raw);
  if (stick) scrollDown(true);
}

// Cierra la burbuja de texto en curso pintando lo que quede pendiente
function closeText() {
  if (curText) markdown(curText.el, curText.raw);
  curText = null;
}

function toolArg(input) {
  if (!input || typeof input !== "object") return "";
  const v = input.command ?? input.file_path ?? input.pattern ?? input.url ?? input.description ?? input.prompt
    ?? Object.values(input).find((x) => typeof x === "string") ?? "";
  return String(v).split("\n")[0].slice(0, 120);
}

function append(node) {
  const stick = nearBottom();
  $("cl-msgs").insertBefore(node, working?.isConnected ? working : null);
  if (stick) scrollDown(true);
}

function render(ev) {
  switch (ev.t) {
    case "user": {
      closeText();
      const m = ev.d.match(ATTACH_RE);
      const text = m ? ev.d.slice(0, m.index) : ev.d;
      const paths = m ? m[1].split("\n").map((l) => l.replace(/^- /, "").trim()).filter(Boolean) : [];
      append(el("div", { class: "msg msg-user" }, text,
        paths.length ? el("div", { class: "msg-files" }, paths.map((p) => el("span", { class: "chip" }, "📎 ",
          el("span", {}, p.split("/").pop().replace(/^\d{8}-\d{6}-/, ""))))) : null));
      break;
    }
    case "text":
      if (!curText) {
        curText = { el: el("div", { class: "msg msg-ai" }), raw: "" };
        append(curText.el);
      }
      curText.raw += ev.d;
      if (ev.replay === undefined && ev.n === undefined) flushText();  // historial: de golpe
      else if (!mdQueued) { mdQueued = true; requestAnimationFrame(flushText); }
      break;
    case "tool": {
      closeText();
      const state = el("span", { class: "tool-state muted" }, "…");
      const body = el("div", { class: "tool-body" }, el("pre", {}, JSON.stringify(ev.input, null, 2)));
      const node = el("details", { class: "tool" },
        el("summary", {}, el("span", { class: "tool-name" }, ev.name), el("span", { class: "tool-arg" }, toolArg(ev.input)), state),
        body);
      tools[ev.id] = { state, body };
      append(node);
      break;
    }
    case "tool_result": {
      const t = tools[ev.id];
      if (!t) break;
      t.state.textContent = ev.error ? "✗" : "✓";
      t.state.className = `tool-state ${ev.error ? "err" : "muted"}`;
      t.body.append(el("pre", {}, ev.output || "(sin salida)"));
      break;
    }
    case "done":
      closeText();
      if (ev.error) append(el("div", { class: "notice" }, `Claude: ${ev.error}`));
      break;
    case "stopped":
      closeText();
      append(el("div", { class: "working" }, "■ Parado"));
      break;
    case "error":
      closeText();
      append(el("div", { class: "notice" }, ev.msg));
      break;
  }
}

function updateRunningUi() {
  const busyHere = running && inChat && (runningSid === sid || (pendingNew && sid == null));
  $("cl-send").hidden = busyHere;
  $("cl-stop").hidden = !busyHere;
  if (busyHere && !working?.isConnected) {
    working = el("div", { class: "working" }, el("i"), el("i"), el("i"), "Claude está trabajando");
    $("cl-msgs").append(working);
    scrollDown();
  } else if (!busyHere && working) {
    working.remove();
    working = null;
  }
  renderSessions();
}

/* ---------- Pantallas ---------- */

async function loadSessions() {
  try {
    [sessions, lastReport] = await Promise.all([api("/api/claude/sessions"), api("/api/report").catch(() => null)]);
    renderSessions();
  } catch (e) {
    if (e.message !== "no autenticado") toast(`Claude: ${e.message}`, true);
  }
}

function reportCard() {
  const r = lastReport;
  if (!r?.summary || !r.session) return null;
  const when = new Date(r.finished * 1000).toLocaleString("es-ES", { weekday: "short", hour: "2-digit", minute: "2-digit" });
  return el("li", {}, el("button", { class: "cl-item cl-report", onclick: () => openChat(r.session, "Resumen del servidor") },
    el("div", { class: "cl-item-sub" }, `Último resumen · ${when}`),
    el("div", { class: "cl-report-text" }, r.summary)));
}

function renderSessions() {
  if (!sessions.length) {
    $("cl-sessions").replaceChildren(el("li", { class: "empty" }, "Aún no hay conversaciones"));
    return;
  }
  $("cl-sessions").replaceChildren(reportCard() || "", ...sessions.map((s) => el("li", {},
    el("button", { class: `cl-item ${inChat && s.id === sid ? "active" : ""}`, onclick: () => openChat(s.id, s.title) },
      el("div", { class: "cl-item-title" },
        running && runningSid === s.id ? el("i", { class: "dot" }) : null,
        el("span", {}, s.title)),
      el("div", { class: "cl-item-sub" }, fmtAgo(s.updated))))));
}

function showScreen(chat) {
  inChat = chat;
  $("cl-list-screen").hidden = chat;
  $("cl-chat-screen").hidden = !chat;
}

function resetChat(title) {
  renderSessions();
  $("cl-msgs").replaceChildren();
  $("cl-title").textContent = title;
  curText = null;
  tools = {};
  working = null;
}

async function openChat(id, title) {
  showScreen(true);
  sid = id;
  pendingNew = false;
  syncing = true;
  resetChat(title || "Conversación");
  try {
    const data = await api(`/api/claude/sessions/${id}`);
    $("cl-title").textContent = data.title;
    for (const m of data.messages) render(m);
    closeText();
    scrollDown(true);
  } catch (e) {
    toast(`No se pudo cargar: ${e.message}`, true);
  }
  attach(id);
}

function newChat() {
  showScreen(true);
  sid = null;
  pendingNew = false;
  syncing = false;
  resetChat("Nueva conversación");
  updateRunningUi();
  $("cl-input").focus();
}

function backToList() {
  showScreen(false);
  sid = null;
  pendingNew = false;
  loadSessions();
}

function renderFiles() {
  const box = $("cl-files");
  box.hidden = !files.length;
  box.replaceChildren(...files.map((f, i) => el("span", { class: "chip" }, "📎 ", el("span", {}, f.name),
    el("button", { type: "button", "aria-label": `Quitar ${f.name}`, onclick: () => { files.splice(i, 1); renderFiles(); } }, "✕"))));
}

async function uploadFiles() {
  const paths = [];
  for (const f of files) {
    if (f.size > 25 * 1024 * 1024) throw new Error(`${f.name}: máximo 25 MB`);
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch("/api/claude/upload", { method: "POST", body: fd, credentials: "same-origin" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `error ${res.status}`);
    paths.push(data.path);
  }
  return paths;
}

async function sendMessage() {
  const input = $("cl-input");
  let text = input.value.trim();
  if (!text && !files.length) return;
  if (running) { toast("Claude está ocupado con otro mensaje", true); return; }
  if (files.length) {
    $("cl-send").disabled = true;
    try {
      const paths = await uploadFiles();
      text = `${text || "Mira estos archivos."}\n\n[Archivos adjuntos para Claude:\n${paths.map((p) => `- ${p}`).join("\n")}]`;
    } catch (e) {
      toast(`No se pudo subir: ${e.message}`, true);
      return;
    } finally {
      $("cl-send").disabled = false;
    }
  }
  if (!wsSend({ send: text, session: sid })) return;
  files = [];
  renderFiles();
  if (!sid) {
    pendingNew = true;
    $("cl-title").textContent = (input.value.trim() || "Archivos").split("\n")[0].slice(0, 60);
  }
  input.value = "";
  autosize();
}

function autosize() {
  const t = $("cl-input");
  t.style.height = "auto";
  t.style.height = `${Math.min(t.scrollHeight, 160)}px`;
}

export function init() {
  $("cl-new").onclick = newChat;
  $("cl-diag").onclick = () => {
    if (running) return toast("Claude está ocupado con otra cosa; prueba en un rato", true);
    newChat();
    $("cl-input").value = panel.claude.diagnosis;
    sendMessage();
  };
  $("cl-report").onclick = async () => {
    try {
      await api("/api/report", { method: "POST" });
      toast("Claude está revisando el server; te aviso cuando acabe (tarda un par de minutos)");
    } catch (e) {
      toast(e.message, true);
    }
  };
  $("cl-back").onclick = backToList;
  $("cl-form").addEventListener("submit", (e) => { e.preventDefault(); sendMessage(); });
  $("cl-input").addEventListener("input", autosize);
  $("cl-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendMessage(); }
  });
  $("cl-stop").onclick = () => wsSend({ stop: true });
  $("cl-file").addEventListener("change", (e) => {
    files.push(...e.target.files);
    e.target.value = "";
    renderFiles();
  });
  document.addEventListener("visibilitychange", () => {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ visible: !document.hidden }));
  });
  $("cl-term").onclick = () => {
    if (!sid) return toast("Manda algún mensaje primero", true);
    if (running && runningSid === sid && !confirm("Claude sigue trabajando en esta conversación. ¿Abrirla igualmente en la terminal?")) return;
    location.hash = `#terminal/resume/${sid}`;
  };
  connectWs();
}

export function show(args = []) {
  // Desde una notificación: #claude/<id>
  if (args[0]) {
    history.replaceState(null, "", "#claude");
    if (args[0] !== sid || !inChat) openChat(args[0]);
    return;
  }
  if (!inChat) loadSessions();
}
