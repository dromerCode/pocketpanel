// Tailscale: los dispositivos de la tailnet con una lucecita (conectado o no), en Estado.
import { api, el, fmtAgo } from "/js/api.js";

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

export async function loadTailscale() {
  try {
    const t = await api("/api/tailscale");
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
