import { api } from "./api.js";

// Hoja lateral/inferior genérica (#usheet): fichas y formularios
const $ = (id) => document.getElementById(id);

export function openSheet(title, sub, ...body) {
  $("us-title").textContent = title;
  $("us-sub").textContent = sub || "";
  $("us-body").replaceChildren(...body.filter((x) => x != null));
  $("usheet").hidden = false;
}

export function closeSheet() {
  $("usheet").hidden = true;
}

let wired = false;
export function initSheet() {
  if (wired) return;
  wired = true;
  $("us-close").onclick = closeSheet;
  $("usheet").addEventListener("click", (e) => { if (e.target.id === "usheet") closeSheet(); });
}

/* ---------- Ventana de salida (#runner): acciones, actualizaciones, restauraciones… ---------- */

const onClose = new Set();

export function closeRunner() {
  $("runner").hidden = true;
  for (const fn of onClose) fn();
  onClose.clear();
}

/** Abre la ventana de salida. `onclose` se llama al cerrarla (para cortar un WebSocket, un temporizador…). */
export function openRunner(title, status, onclose) {
  closeRunner();
  $("run-title").textContent = title;
  setRunnerStatus(status);
  $("run-out").textContent = "";
  if (onclose) onClose.add(onclose);
  $("runner").hidden = false;
}

export function setRunnerStatus(text, ok = null) {
  $("run-status").textContent = text;
  $("run-status").style.color = ok == null ? "" : ok ? "var(--accent)" : "var(--danger)";
}

export function runnerOut(text, append = false) {
  const out = $("run-out");
  out.textContent = append ? out.textContent + text : text;
  out.scrollTop = out.scrollHeight;
}

/** Sigue una tarea larga del servidor (GET `url` → {status, lines}) hasta que deja de estar "running".
 * `results`: { estado: [texto, ok] } para el final; `ondone` se llama al acabar. */
export function watchJob(url, title, results, ondone) {
  let timer = null;
  openRunner(title, "en marcha… (puedes cerrar esto, sigue en el servidor)", () => clearInterval(timer));
  const poll = async () => {
    try {
      const j = await api(url);
      runnerOut(j.lines.join("\n"));
      if (j.status !== "running") {
        clearInterval(timer);
        const [text, ok] = results[j.status] || [j.status, j.status !== "failed"];
        setRunnerStatus(text, ok);
        ondone?.(j);
      }
    } catch (e) {
      setRunnerStatus(`sin conexión, reintento… (${e.message})`);
    }
  };
  poll();
  timer = setInterval(poll, 1500);
}

export function initRunner() {
  $("run-close").onclick = closeRunner;
  $("runner").addEventListener("click", (e) => { if (e.target.id === "runner") closeRunner(); });
}
