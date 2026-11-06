// El widget de ntfy: mensajes de todos los temas (o de uno, con los chips) y la hoja para suscribirse.
import { api, el, fmtAgo, toast } from "/js/api.js";
import { initSheet, openSheet } from "/js/ui.js";

const $ = (id) => document.getElementById(id);
const PRIO = { 4: "alta", 5: "urgente" };
// Las etiquetas que ntfy enseña como emoji (las más usadas); el resto sale como texto.
const EMOJI = { warning: "⚠️", rotating_light: "🚨", white_check_mark: "✅", heavy_check_mark: "✔️", x: "❌",
  no_entry: "⛔", tada: "🎉", fire: "🔥", skull: "💀", bell: "🔔", loudspeaker: "📢", "+1": "👍", "-1": "👎",
  information_source: "ℹ️", computer: "💻", money_with_wings: "💸", moneybag: "💰" };

let state = null;
let only = null; // tema elegido en los chips (null = todos)
const opened = new Set(); // mensajes largos que se han abierto (siguen abiertos al refrescar)

const link = (href, text) => el("a", { href, target: "_blank", rel: "noopener noreferrer" }, text);

function row(m, showTopic) {
  const emoji = m.tags.filter((t) => EMOJI[t]).map((t) => EMOJI[t]).join("");
  const words = m.tags.filter((t) => !EMOJI[t]);
  const title = [emoji, m.title].filter(Boolean).join(" ");
  return el("li", { class: `ntfy-item${m.priority >= 4 ? ` p${m.priority}` : ""}` },
    title ? el("b", { class: "ntfy-title" }, title) : null,
    m.message ? el("div", { class: `ntfy-msg${opened.has(m.id) ? " open" : ""}`, title: "Toca para verlo entero",
      onclick: (e) => opened[e.currentTarget.classList.toggle("open") ? "add" : "delete"](m.id) }, m.message) : null,
    m.attachment ? link(m.attachment.url, `📎 ${m.attachment.name}`) : null,
    el("div", { class: "ntfy-meta" },
      PRIO[m.priority] ? el("span", { class: `ntfy-prio p${m.priority}` }, PRIO[m.priority]) : null,
      el("span", { title: new Date(m.time * 1000).toLocaleString("es-ES") }, fmtAgo(m.time)),
      showTopic ? el("span", { class: "ntfy-topic-name" }, m.topic) : null,
      words.length ? el("span", {}, words.join(", ")) : null,
      m.click ? link(m.click, "Abrir ↗") : null));
}

function chip(t) {
  return el("button", { type: "button", class: only === t ? "on" : null, onclick: () => { only = t; render(); } }, t ?? "Todos");
}

function render() {
  const s = state, many = s.topics.length > 1;
  if (!s.topics.includes(only)) only = null;
  $("ntfy-filter").hidden = !many;
  $("ntfy-filter").replaceChildren(...(many ? [null, ...s.topics].map(chip) : []));
  const msgs = s.messages.filter((m) => !only || m.topic === only);
  const list = $("ntfy-list"), top = list.scrollTop;
  list.replaceChildren(...[
    s.error ? el("li", { class: "ntfy-err small" }, s.error) : null,
    !s.topics.length ? el("li", { class: "muted small" }, "No sigues ningún tema: pulsa «Temas» para suscribirte.")
      : !msgs.length ? el("li", { class: "muted small" }, "Todavía no ha llegado nada") : null,
    ...msgs.map((m) => row(m, many && !only))].filter(Boolean));
  list.scrollTop = top;
}

export async function loadNtfy() {
  try {
    state = await api("/api/ntfy");
    render();
  } catch (e) {
    if (e.message !== "no autenticado") $("ntfy-list").replaceChildren(el("li", { class: "ntfy-err small" }, e.message));
  }
}

async function change(path, opts, done) {
  try {
    state = await api(path, opts);
    render();
    openTopics();
    if (done) toast(done);
  } catch (e) {
    toast(e.message, true);
  }
}

function openTopics() {
  initSheet();
  const host = state.server.replace(/^https?:\/\//, "");
  const input = el("input", { type: "text", placeholder: "mi-tema o https://ntfy.sh/mi-tema", autocapitalize: "off",
    autocomplete: "off", spellcheck: "false", enterkeyhint: "done" });
  const subscribe = (e) => {
    e.preventDefault();
    if (input.value.trim()) change("/api/ntfy/topics", { method: "POST", body: { topic: input.value.trim() } }, "Suscrito");
  };
  const topics = state.topics.map((t) => el("div", { class: "ntfy-trow" },
    el("span", { class: "mono" }, t),
    el("button", { class: "btn btn-sm", type: "button",
      onclick: () => change(`/api/ntfy/topics/${encodeURIComponent(t)}`, { method: "DELETE" }) }, "Quitar")));
  openSheet("Temas de ntfy", host,
    topics.length ? el("div", { class: "card ntfy-topics" }, topics) : el("p", { class: "muted small" }, "Aún no sigues ningún tema."),
    el("form", { class: "form", onsubmit: subscribe },
      el("label", {}, "Suscribirse a un tema", input),
      el("button", { class: "btn btn-primary", type: "submit" }, "Suscribirse")),
    el("p", { class: "muted small" }, "Al suscribirte se trae lo que ntfy aún guarda de ese tema (en ntfy.sh, las últimas 12 h). ",
      "En ntfy.sh cualquiera que sepa el nombre de un tema puede leerlo y escribir en él: usa nombres difíciles de adivinar. Para probar:"),
    el("code", { class: "ntfy-try" }, `curl -d "Hola" ${host}/${state.topics[0] || "mi-tema"}`));
  if (!topics.length) input.focus();
}

export function initNtfy() {
  $("ntfy-topics").onclick = async () => {
    if (!state) await loadNtfy();
    if (state) openTopics();
  };
}
