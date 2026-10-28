// Bolsa: cartera, seguimiento, «Descubrir» y ventas. El servidor ya lo da todo en euros.
import { api, el, toast } from "/js/api.js";

const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
let range = "anio";
let data = null;
let timer = null;
let discover = null;  // lo último que encontró «Descubrir» (se reaprovecha al volver a la pestaña)
let discLimit = 10;

try { range = localStorage.getItem("stocks-range") || range; } catch { /* sin almacenamiento */ }

const money = (v) => (v == null ? "—" : v.toLocaleString("es-ES", { style: "currency", currency: "EUR" }));
const pct = (v, d = 2) => (v == null ? "" : `${v >= 0 ? "+" : ""}${v.toFixed(d)} %`);
const conf = (c) => ({ ALTA: "ok", MEDIA: "warn", BAJA: "bad" }[c] || "");

function svg(tag, attrs = {}) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

function nearest(labels, iso) {
  if (!labels?.length || !iso) return -1;
  const t = Date.parse(iso), a = Date.parse(labels[0]), b = Date.parse(labels[labels.length - 1]);
  const pad = (b - a) * 0.02;
  if (t < a - pad || t > b + pad) return -1;  // la compra cae fuera del rango
  let best = 0;
  labels.forEach((l, i) => { if (Math.abs(Date.parse(l) - t) < Math.abs(Date.parse(labels[best]) - t)) best = i; });
  return best;
}

// Gráfica de línea con zona sombreada y marcas de compra; al pasar el dedo enseña el valor de ese momento
function chart(box, prices, { labels, zone, marks = [], onHover, area = false, h = 56 } = {}) {
  box.replaceChildren();
  const vals = (prices || []).filter((v) => v != null);
  if (vals.length < 2) { box.append(el("p", { class: "muted small" }, "Sin datos para este rango.")); return; }
  const w = 300, pad = 3;
  const lo = Math.min(...vals, ...(zone || [])), hi = Math.max(...vals, ...(zone || [])), span = hi - lo || 1;
  const x = (i) => pad + (i / (prices.length - 1)) * (w - 2 * pad);
  const y = (v) => h - pad - ((v - lo) / span) * (h - 2 * pad);
  const up = vals[vals.length - 1] >= vals[0];
  const color = up ? "var(--accent)" : "var(--danger)";
  const s = svg("svg", { viewBox: `0 0 ${w} ${h}`, preserveAspectRatio: "none", class: up ? "up" : "down" });
  if (zone?.length === 2) {
    s.append(svg("rect", { x: 0, y: y(zone[1]), width: w, height: Math.max(1, y(zone[0]) - y(zone[1])), class: "stk-zone" }));
  }
  for (const iso of marks) {
    const i = nearest(labels, iso);
    if (i >= 0) s.append(svg("line", { x1: x(i), x2: x(i), y1: 0, y2: h, class: "stk-mark" }));
  }
  const pts = prices.map((v, i) => (v == null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean);
  if (area) s.append(svg("path", { d: `M${pts.join(" L")} L${x(prices.length - 1)},${h} L${x(0)},${h} Z`, fill: color, opacity: 0.1 }));
  s.append(svg("path", { d: `M${pts.join(" L")}`, fill: "none", stroke: color, "stroke-width": area ? 2 : 1.6,
    "vector-effect": "non-scaling-stroke" }));
  const cursor = svg("line", { y1: 0, y2: h, class: "stk-cursor", opacity: 0 });
  s.append(cursor);
  box.append(s);
  if (!onHover) return;
  const move = (e) => {
    const r = s.getBoundingClientRect();
    const i = Math.max(0, Math.min(prices.length - 1, Math.round(((e.clientX - r.left) / r.width * w - pad) / (w - 2 * pad) * (prices.length - 1))));
    if (prices[i] == null) return;
    cursor.setAttribute("x1", x(i)); cursor.setAttribute("x2", x(i)); cursor.setAttribute("opacity", 1);
    onHover(i);
  };
  const leave = () => { cursor.setAttribute("opacity", 0); onHover(null); };
  s.addEventListener("pointermove", move);
  s.addEventListener("pointerdown", move);
  s.addEventListener("pointerleave", leave);
  s.addEventListener("pointerup", (e) => { if (e.pointerType !== "mouse") leave(); });
}

function when(iso, withTime) {
  const d = new Date(iso);
  return d.toLocaleDateString("es-ES", { day: "numeric", month: "short", year: withTime ? undefined : "numeric" })
    + (withTime ? ` · ${d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}` : "");
}

async function act(fn, ok) {
  try {
    await fn();
    if (ok) toast(ok);
    await load();
  } catch (e) {
    toast(e.message, true);
  }
}

/* ---------- Tarjetas ---------- */

function reasons(rec) {
  if (!rec.detail?.length) return el("p", { class: "muted small" }, rec.reason);
  return el("details", { class: "stk-why" }, el("summary", {}, rec.reason),
    el("ul", {}, rec.detail.map((d) => el("li", {}, d))));
}

function card(item, { rank, extra, actions, zone } = {}) {
  const m = item.market || {}, rec = item.recommendation || {};
  const price = el("span", { class: "stk-price mono" }, money(m.price_eur));
  const change = el("span", { class: `stk-chg ${(m.change_pct || 0) >= 0 ? "up" : "down"}` }, m.change_pct != null ? pct(m.change_pct) : "");
  const slot = el("div", { class: "stk-chart", "data-ticker": item.ticker });
  slot._opts = { zone, price, change, buy: item.bought_at };
  return el("article", { class: "stk-card" },
    el("div", { class: "stk-head" },
      el("div", { class: "stk-name" },
        el("b", {}, rank ? el("span", { class: "muted" }, `#${rank} `) : null, item.ticker),
        el("span", { class: "muted small ellipsis" }, item.name || m.name || "")),
      el("span", { class: `badge ${conf(rec.confidence)}` }, rec.verdict || "—",
        rec.confidence && rec.confidence !== "N/A" ? ` · ${rec.confidence}` : "")),
    el("div", { class: "stk-price-row" }, price, change),
    slot, extra, reasons(rec), actions);
}

function holdingCard(h) {
  const extra = el("div", { class: "stk-kv small" },
    el("span", {}, "Invertido ", el("b", {}, money(h.invested_eur))),
    el("span", {}, "Vale ", el("b", {}, money(h.value_eur))),
    el("span", { class: (h.pl_eur || 0) >= 0 ? "up" : "down" }, el("b", {}, `${h.pl_eur >= 0 ? "+" : ""}${money(h.pl_eur)} (${pct(h.pl_pct, 1)})`)));
  const sell = el("button", { class: "btn btn-sm btn-danger", onclick: () => {
    if (!confirm(`¿Has vendido ${h.ticker}?\n\nSe quita de la cartera y se apunta la venta al precio de ahora. No se ejecuta ninguna orden: hazla en tu bróker.`)) return;
    act(() => api(`/api/stocks/holdings/${h.ticker}/sell`, { method: "POST" }), `${h.ticker} vendida`);
  } }, "Vender");
  return card(h, { extra, actions: el("div", { class: "btn-row" }, sell) });
}

function watchCard(w) {
  const m = w.market || {};
  const zone = w.entry_zone && m.rate ? w.entry_zone.map((v) => v / m.rate) : null;
  const extra = el("div", { class: "stk-kv small" },
    el("span", {}, "Zona ", el("b", {}, zone ? `${money(zone[0])} – ${money(zone[1])}` : "—")),
    el("span", {}, "RSI ", el("b", {}, m.rsi14 ?? "—")));
  const amount = el("input", { type: "number", step: "any", inputmode: "decimal", placeholder: "€ a invertir" });
  const buy = el("button", { class: "btn btn-sm btn-primary", onclick: () => {
    const v = parseFloat(amount.value);
    if (!(v > 0)) { amount.focus(); toast("Escribe cuántos € has invertido", true); return; }
    if (!confirm(`¿Apunto la compra de ${w.ticker} por ${money(v)}?\n\nNo se ejecuta ninguna orden: hazla en tu bróker.`)) return;
    act(() => api(`/api/stocks/watchlist/${w.ticker}/buy`, { method: "POST", body: { invested_eur: v } }), `${w.ticker} a cartera`);
  } }, "Comprar");
  const drop = el("button", { class: "btn btn-sm", "aria-label": `Dejar de seguir ${w.ticker}`, onclick: () => {
    if (confirm(`¿Dejar de seguir ${w.ticker}?`)) act(() => api(`/api/stocks/watchlist/${w.ticker}`, { method: "DELETE" }));
  } }, "✕");
  return card(w, { zone, extra, actions: el("div", { class: "stk-buy" }, amount, buy, drop) });
}

function discoverCard(p, i) {
  const add = el("button", { class: "btn btn-sm", onclick: async () => {
    add.disabled = true;
    add.textContent = "Añadiendo…";
    try {
      await api("/api/stocks/watchlist", { method: "POST", body: { ticker: p.ticker } });
      add.textContent = "✓ En seguimiento";
      discover.picks = discover.picks.filter((x) => x.ticker !== p.ticker);
      load();
    } catch (e) {
      add.disabled = false;
      add.textContent = "+ Seguir";
      toast(e.message, true);
    }
  } }, "+ Seguir");
  return card(p, { rank: i + 1, actions: el("div", { class: "btn-row" }, add) });
}

/* ---------- Pintar ---------- */

function render() {
  const d = data;
  const total = d.value_eur + Math.max(d.cash_eur, 0);
  const cash = el("button", { class: "linklike", title: "Cambiar", onclick: () => {
    const v = prompt("Efectivo disponible (€):", String(d.cash_eur).replace(".", ","));
    if (v == null) return;
    act(() => api("/api/stocks/cash", { method: "PUT", body: { cash_eur: Number(v.replace(",", ".")) } }), "Efectivo cambiado");
  } }, money(d.cash_eur), " ✎");
  const pl = d.value_eur - d.invested_eur;
  $("stk-totals").replaceChildren(
    el("span", {}, "Total ", el("b", {}, money(total))),
    el("span", {}, "Efectivo ", cash),
    el("span", {}, "Invertido ", el("b", {}, money(d.invested_eur))),
    d.invested_eur ? el("span", { class: pl >= 0 ? "up" : "down" }, "Abierto ", el("b", {}, `${pl >= 0 ? "+" : ""}${money(pl)}`)) : null,
    el("span", { class: d.realized_pl_eur >= 0 ? "up" : "down" }, "Cerrado ", el("b", {}, `${d.realized_pl_eur >= 0 ? "+" : ""}${money(d.realized_pl_eur)}`)));
  $("stk-pos-count").textContent = `${d.holdings.length}/${d.max_positions}`;
  $("stk-holdings").replaceChildren(...(d.holdings.length ? d.holdings.map(holdingCard)
    : [el("p", { class: "muted small" }, "Sin posiciones.")]));
  $("stk-watch").replaceChildren(...(d.watchlist.length ? d.watchlist.map(watchCard)
    : [el("p", { class: "muted small" }, "No sigues ningún valor.")]));
  $("stk-sold").replaceChildren(...d.sold.slice(0, 12).map((s) => {
    const r = s.realized_pl_eur;  // en euros, con el cambio de cada momento
    return el("li", {}, el("span", {}, el("b", {}, s.ticker), el("span", { class: "muted small" }, ` ${when(s.sold_at)}`)),
      el("span", { class: `mono ${r >= 0 ? "up" : "down"}` }, `${r >= 0 ? "+" : ""}${money(r)}${s.invested_eur ? ` (${pct(r / s.invested_eur * 100, 1)})` : ""}`));
  }));
  if (!d.sold.length) $("stk-sold").append(el("li", { class: "muted small" }, "Nada todavía."));
  renderDiscover();
}

function renderDiscover() {
  const box = $("stk-discover");
  if (!discover) return;
  box.replaceChildren(...(discover.picks.length ? discover.picks.map(discoverCard)
    : [el("p", { class: "muted small" }, `Nada en zona de compra ni de entrada ahora mismo (${discover.scanned} revisadas).`)]));
  const more = $("stk-disc-more");
  more.hidden = discover.total_candidates <= 10;
  more.textContent = discLimit >= 20 ? "Top 10" : `Top 20 (${discover.total_candidates})`;
  charts(discover.picks.map((p) => p.ticker));
}

async function charts(tickers) {
  if (!tickers.length) return;
  let c;
  try {
    c = await api(`/api/stocks/chart?tickers=${tickers.join(",")}&range=${range}`);
  } catch { return; }
  const zoneOn = range === "anio" || range === "mes";
  for (const slot of document.querySelectorAll("#view-stocks .stk-chart[data-ticker]")) {
    const s = c[slot.dataset.ticker];
    if (!s) continue;
    const o = slot._opts || {};
    const live = o.price?.textContent;
    chart(slot, s.prices, { labels: s.labels, zone: zoneOn ? o.zone : null, marks: o.buy ? [o.buy] : [],
      onHover: (i) => { if (o.price) o.price.textContent = i == null ? live : money(s.prices[i]); } });
    if (o.change && s.prices.length > 1) {  // la variación del rango elegido
      const a = s.prices.find((v) => v != null), b = s.prices[s.prices.length - 1];
      o.change.textContent = pct((b - a) / a * 100);
      o.change.className = `stk-chg ${b >= a ? "up" : "down"}`;
    }
  }
}

async function hero() {
  let hst;
  try {
    hst = await api(`/api/stocks/history?range=${range}`);
  } catch { return; }
  const v = hst.values_eur;
  if (!v.length) {
    $("stk-value").textContent = money(data?.value_eur);
    $("stk-sub").textContent = data?.holdings.length ? "Sin datos para este rango" : "Sin posiciones abiertas";
    $("stk-hero-chart").replaceChildren();
    return;
  }
  const last = v[v.length - 1], change = (last - v[0]) / v[0] * 100;
  const sub = () => { $("stk-sub").replaceChildren(el("span", { class: change >= 0 ? "up" : "down" }, pct(change, 1)), " en el rango"); };
  $("stk-value").textContent = money(last);
  sub();
  chart($("stk-hero-chart"), v, { labels: hst.labels, marks: hst.buy_dates, area: true, h: 110, onHover: (i) => {
    if (i == null) { $("stk-value").textContent = money(last); sub(); return; }
    $("stk-value").textContent = money(v[i]);
    $("stk-sub").textContent = when(hst.labels[i], range === "dia" || range === "semana");
  } });
}

async function load() {
  try {
    data = await api("/api/stocks");
  } catch (e) {
    if (e.message !== "no autenticado") $("stk-sub").textContent = e.message;
    return;
  }
  render();
  await Promise.all([hero(), charts([...data.holdings, ...data.watchlist].map((x) => x.ticker))]);
  clearTimeout(timer);
  timer = setTimeout(load, data.market_open ? 60_000 : 300_000);
}

async function scan(limit) {
  discLimit = limit;
  const btn = $("stk-disc-btn");
  btn.disabled = true;
  $("stk-discover").replaceChildren(el("p", { class: "muted small" }, "Revisando la lista… (la primera vez tarda unos 20 s)"));
  try {
    discover = await api(`/api/stocks/discover?limit=${limit}`);
    renderDiscover();
  } catch (e) {
    $("stk-discover").replaceChildren(el("p", { class: "form-error" }, e.message));
  } finally {
    btn.disabled = false;
    btn.textContent = "Refrescar";
  }
}

/* ---------- Ciclo de vida ---------- */

export function init() {
  for (const b of document.querySelectorAll("#stk-range .seg-btn")) {
    b.classList.toggle("active", b.dataset.range === range);
    b.onclick = () => {
      range = b.dataset.range;
      try { localStorage.setItem("stocks-range", range); } catch { /* sin almacenamiento */ }
      for (const o of document.querySelectorAll("#stk-range .seg-btn")) o.classList.toggle("active", o === b);
      hero();
      charts([...document.querySelectorAll("#view-stocks .stk-chart[data-ticker]")].map((s) => s.dataset.ticker));
    };
  }
  $("stk-disc-btn").onclick = () => scan(discLimit);
  $("stk-disc-more").onclick = () => scan(discLimit >= 20 ? 10 : 20);
  $("stk-add").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    act(async () => {
      await api("/api/stocks/watchlist", { method: "POST", body: { ticker: f.ticker.value, entry_low: f.low.value, entry_high: f.high.value } });
      f.reset();
    }, "Añadido a seguimiento");
  });
  $("stk-digest").onclick = () => act(async () => {
    const r = await api("/api/stocks/digest", { method: "POST" });
    toast(`Enviado: ${r.sent} valores`);
  });
}

export function show() {
  load();
  if (!discover) scan(discLimit);
}

export function hide() {
  clearTimeout(timer);
}

export async function loadCard() {
  // La gráfica, con el mismo rango que la pestaña Bolsa; las series las cachea el servidor 5 min
  api(`/api/stocks/history?range=${range}`)
    .then((h) => chart($("stk-card-chart"), h.values_eur, { labels: h.labels, marks: h.buy_dates, area: true, h: 64 }))
    .catch(() => $("stk-card-chart").replaceChildren());
  try {
    const d = await api("/api/stocks");
    const pl = d.value_eur - d.invested_eur;
    const today = d.holdings.reduce((s, h) => s + (h.value_eur || 0) * (h.market?.change_pct || 0) / (100 + (h.market?.change_pct || 0)), 0);
    $("stk-card-value").textContent = money(d.value_eur + Math.max(d.cash_eur, 0));
    $("stk-card-sub").textContent = d.holdings.length
      ? `${d.holdings.length} posiciones · hoy ${today >= 0 ? "+" : ""}${money(today)} · abierto ${pl >= 0 ? "+" : ""}${money(pl)}`
      : "Sin posiciones abiertas";
  } catch (e) {
    if (e.message !== "no autenticado") $("stk-card-sub").textContent = e.message;
  }
}
