import { api, el, toast, wsUrl } from "/js/api.js";
import { openRunner, runnerOut, setRunnerStatus } from "/js/ui.js";

const $ = (id) => document.getElementById(id);

function run(a) {
  if (a.confirm && !confirm(`¿Ejecutar "${a.name}"?\n\n${a.cmd}`)) return;
  const ws = new WebSocket(wsUrl(`/ws/action/${a.id}`));
  openRunner(a.name, "ejecutando…", () => ws.close());
  runnerOut(`$ ${a.cmd}\n`);
  ws.onmessage = (e) => {
    let msg = null;
    if (e.data.startsWith("{")) { try { msg = JSON.parse(e.data); } catch { /* era salida normal */ } }
    if (msg && ("exit" in msg || "error" in msg)) {
      const ok = msg.exit === 0;
      setRunnerStatus(msg.error ? msg.error : ok ? "✓ terminado" : `✗ salió con código ${msg.exit}`, ok);
      return;
    }
    runnerOut(e.data, true);
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
