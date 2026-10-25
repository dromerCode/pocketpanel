// Descargas: tarjeta en Estado (velocidades) y su vista (#downloads) con torrents, cola y estrenos.
import { api } from "/js/api.js";
import * as view from "./downloads.js";

const $ = (id) => document.getElementById(id);
const { speed } = view;

async function loadDownloads() {
  try {
    const d = await api("/api/downloads/summary");
    $("dl-down").textContent = `↓ ${speed(d.dl)}`;
    $("dl-up").textContent = `↑ ${speed(d.up)}`;
    $("dl-sub").textContent = d.error || [`${d.active} activas`, d.paused ? `${d.paused} en pausa` : null].filter(Boolean).join(" · ");
    $("dl-sub").classList.toggle("bad", !!d.error);
  } catch (e) {
    if (e.message !== "no autenticado") $("dl-sub").textContent = e.message;
  }
}

export default {
  styles: ["style.css"],
  view: { html: "view.html" },
  cards: [{ slot: "left", html: "card.html", order: 1, show: loadDownloads, fast: loadDownloads }],
  show: view.show,
  hide: view.hide,
};
