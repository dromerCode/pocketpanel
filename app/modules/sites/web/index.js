// Webs y certificados, en Estado.
import { api, el } from "/js/api.js";

const $ = (id) => document.getElementById(id);

function siteRow(s) {
  const cert = s.cert_days == null ? "" : `🔒 ${s.cert_days} d`;
  const certCls = s.cert_days == null ? "" : s.cert_days < 0 || s.cert_days <= 3 ? "cert-bad" : s.cert_days <= 14 ? "cert-warn" : "";
  return el("li", {},
    el("i", { class: `dot ${s.ok === false ? "off" : ""}`, style: s.ok == null ? "background:var(--muted)" : null }),
    el("a", { class: "site-name", href: s.url, target: "_blank", rel: "noopener" }, s.name),
    el("span", { class: "site-meta" }, s.ms != null ? `${s.ms} ms ` : "", el("span", { class: certCls }, cert)),
    s.ok === false ? el("span", { class: "site-err" }, s.error) : null);
}

async function loadSites(fresh = false) {
  try {
    const list = await api(fresh ? "/api/sites/check" : "/api/sites", fresh ? { method: "POST" } : {});
    $("sites").replaceChildren(...(list.length ? list.map(siteRow)
      : [el("li", { class: "muted small" }, "Añade webs en ⚙ → Webs y certificados")]));
  } catch (e) {
    if (e.message !== "no autenticado") $("sites").replaceChildren(el("li", { class: "muted small" }, e.message));
  }
}

export default {
  styles: ["style.css"],
  cards: [{
    slot: "right", html: "card.html", slow: () => loadSites(),
    init() {
      $("sites-check").onclick = () => { $("sites").replaceChildren(el("li", { class: "muted small" }, "Comprobando…")); loadSites(true); };
    },
  }],
};
