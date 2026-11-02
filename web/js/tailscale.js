// El widget Tailscale de Estado: los dispositivos de la tailnet con una lucecita (conectado o no). Oculto no pide
// nada; si el servidor no tiene Tailscale, el widget se quita.
import { api, el, fmtAgo } from "./api.js";

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
  if (!widget() || widget().hidden) return;
  try {
    const t = await api("/api/tailscale");
    if (t.state === "absent") {
      widget().remove();
      return;
    }
    const badge = $("ts-badge");
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
    $("ts-badge").textContent = "Sin datos";
    $("ts-list").replaceChildren(el("li", { class: "muted small" }, e.message));
  }
}

export function initTailscale() {
  widget()?.addEventListener("wshow", loadTailscale);
}
