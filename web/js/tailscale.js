// El widget Tailscale de Estado: los dispositivos de la tailnet con una lucecita (conectado o no). Oculto no pide
// nada. Si el servidor no tiene Tailscale no sale (data-absent, con el que ya empieza en index.html), pero sigue en
// la rejilla: su sitio y su ancho no se pierden al guardar, y vuelve solo si aparece Tailscale.
import { api, el, fmtAgo, toast } from "./api.js";
import { layoutReady } from "./widgets.js";

const $ = (id) => document.getElementById(id);
const OS = { linux: "Linux", windows: "Windows", macOS: "Mac", iOS: "iPhone", android: "Android", freebsd: "FreeBSD" };

function row(d) {
  const sub = [OS[d.os] || d.os, d.me ? "este servidor" : d.online ? "conectado" : d.last_seen ? `visto ${fmtAgo(d.last_seen)}` : "desconectado",
    d.exit_node ? "nodo de salida" : null].filter(Boolean).join(" · ");
  return el("li", { class: d.online ? "" : "off", title: d.dns },
    el("span", { class: `light ${d.online ? "ok" : "unknown"}`, role: "img", "aria-label": d.online ? "conectado" : "desconectado" }),
    el("span", { class: "ts-name" }, d.name, d.me ? el("span", { class: "ts-me" }, "este") : null),
    el("span", { class: "ts-ip mono" }, d.ip || ""),
    el("span", { class: "ts-sub" }, sub));
}

const widget = () => document.querySelector('#st-grid > [data-w="tailscale"]');

export async function loadTailscale() {
  await layoutReady;
  const w = widget();
  if (!w || w.hidden) return;
  const badge = $("ts-badge");
  try {
    const t = await api("/api/tailscale");
    if (t.state === "absent") {
      w.dataset.absent = "";
      return;
    }
    delete w.dataset.absent;
    if (t.state !== "Running") {
      badge.textContent = t.state === "error" ? "Sin datos" : t.state === "Stopped" ? "Apagado" : t.state;
      badge.className = "badge warn";
      $("ts-list").replaceChildren(el("li", { class: "muted small" }, t.error || "Tailscale no está conectado en el servidor"));
      return;
    }
    badge.textContent = `${t.online} de ${t.devices.length} conectados`;
    badge.className = "badge ok";
    $("ts-list").replaceChildren(...t.devices.map(row));
  } catch (e) {
    if (e.message === "no autenticado") return;
    delete w.dataset.absent;
    badge.textContent = "Sin datos";
    badge.className = "badge warn";
    $("ts-list").replaceChildren(el("li", { class: "muted small" }, e.message));
  }
}

export function initTailscale() {
  widget()?.addEventListener("wshow", async () => {  // sacado de ocultos: si no hay Tailscale, que no parezca que no ha hecho nada
    await loadTailscale();
    if ("absent" in widget().dataset) toast("Este servidor no tiene Tailscale");
  });
}
