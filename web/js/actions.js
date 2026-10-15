import { api, el, toast, wsUrl } from "./api.js";

const $ = (id) => document.getElementById(id);
let ws = null;

function close() {
  ws?.close();
  ws = null;
  $("runner").hidden = true;
}

function run(a) {
  if (a.confirm && !confirm(`¿Ejecutar "${a.name}"?\n\n${a.cmd}`)) return;
  $("run-title").textContent = a.name;
  $("run-status").textContent = "ejecutando…";
  $("run-status").style.color = "";
  $("run-out").textContent = `$ ${a.cmd}\n`;
  $("runner").hidden = false;
  ws = new WebSocket(wsUrl(`/ws/action/${a.id}`));
  ws.onmessage = (e) => {
    let msg = null;
    if (e.data.startsWith("{")) { try { msg = JSON.parse(e.data); } catch { /* era salida normal */ } }
    if (msg && ("exit" in msg || "error" in msg)) {
      const ok = msg.exit === 0;
      $("run-status").textContent = msg.error ? msg.error : ok ? "✓ terminado" : `✗ salió con código ${msg.exit}`;
      $("run-status").style.color = ok ? "var(--accent)" : "var(--danger)";
      return;
    }
    const out = $("run-out");
    out.textContent += e.data;
    out.scrollTop = out.scrollHeight;
  };
  ws.onclose = (e) => { if (e.code === 4401) location.reload(); };
}

export async function loadActions() {
  try {
    const acts = await api("/api/actions");
    $("actions").replaceChildren(...(acts.length
      ? acts.map((a) => el("button", { class: "btn", onclick: () => run(a) }, a.name))
      : [el("p", { class: "muted small" }, "No hay acciones en actions.yml")]));
  } catch (e) {
    if (e.message !== "no autenticado") toast(`Acciones: ${e.message}`, true);
  }
}

export function initActions() {
  $("run-close").onclick = close;
  $("runner").addEventListener("click", (e) => { if (e.target.id === "runner") close(); });
}
