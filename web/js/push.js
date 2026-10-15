import { api, toast } from "./api.js";

const btn = () => document.getElementById("push-btn");

function keyBytes(b64) {
  const s = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}

async function current() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return null;
  const reg = await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

async function refresh() {
  const sub = await current().catch(() => null);
  btn().textContent = sub ? "🔔" : "🔕";
  btn().title = sub ? "Avisos activados (toca para quitarlos)" : "Activar avisos";
}

async function toggle() {
  if (!window.isSecureContext || !("PushManager" in window)) {
    return toast("Los avisos necesitan abrir la app por https (la URL .ts.net:8443)", true);
  }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  try {
    if (sub) {
      await api("/api/push/unsubscribe", { method: "POST", body: { endpoint: sub.endpoint } });
      await sub.unsubscribe();
      toast("Avisos desactivados en este móvil");
    } else {
      if ((await Notification.requestPermission()) !== "granted") return toast("Sin permiso para notificaciones", true);
      const { key } = await api("/api/push/key");
      const s = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
      await api("/api/push/subscribe", { method: "POST", body: s.toJSON() });
      await api("/api/push/test", { method: "POST" });
      toast("Avisos activados: te he mandado uno de prueba");
    }
  } catch (e) {
    toast(`Avisos: ${e.message}`, true);
  }
  refresh();
}

export function initPush() {
  btn().onclick = toggle;
  refresh();
}
