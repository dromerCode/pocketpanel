import { api, el, toast } from "/js/api.js";
import { closeSheet, initSheet, openSheet } from "/js/ui.js";
import { monthText, num, pct, round2, totalOf } from "./calc.js";

const sheet = (title, sub, ...body) => openSheet(title, sub, ...body.flat(Infinity));

const $ = (id) => document.getElementById(id);
let S = null;          // todo lo que devuelve /api/cobros

const EUR = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" });
const eur = (n) => EUR.format(n || 0);
const eur0 = (n) => (Number.isInteger(n) ? `${n.toLocaleString("es-ES")} €` : eur(n));  // 120 € en vez de 120,00 €
const METHODS = [["transferencia", "Transferencia"], ["efectivo", "Efectivo"], ["bizum", "Bizum"], ["tarjeta", "Tarjeta"], ["otro", "Otro"]];
const PAID_AS = { transferencia: "Pagada por transferencia", efectivo: "Pagada en efectivo", bizum: "Pagada por Bizum", tarjeta: "Pagada con tarjeta", otro: "Pagada" };
const PERIOD = { month: ["Mensual", "al mes"], quarter: ["Trimestral", "al trimestre"], year: ["Anual", "al año"] };
const STEP = { month: 1, quarter: 3, year: 12 };

const D = (iso) => new Date(`${iso}T12:00:00`);
const fd = (iso) => (iso ? D(iso).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" }) : "—");
const dmy = (iso) => D(iso).toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit", year: "numeric" });
const dec = (n) => (n == null || n === "" ? "" : (Number.isInteger(+n) ? String(+n) : (+n).toFixed(2)).replace(".", ","));

const client = (id) => S.clients.find((c) => c.id === id);
const charge = (id) => S.charges.find((c) => c.id === id);
const who = (c) => client(c.client)?.name || c.who || "—";

function planOf(sub) {
  const prod = S.products.find((p) => p.id === sub?.product);
  return { prod, plan: prod?.plans.find((p) => p.id === sub.plan) };
}

function subOf(c) { return c.sub ? S.subs.find((s) => s.id === c.sub) : null; }

// "MiERP · Básico" en vez de "Suscripción anual a MiERP, plan Básico"
function shortConcept(c) {
  const { prod, plan } = planOf(subOf(c));
  return prod && plan ? `${prod.name} · ${plan.name} (${PERIOD[plan.period][0].toLowerCase()})` : c.concept;
}

function monthly(c) {
  const { plan } = planOf(subOf(c));
  return plan ? plan.period === "month" : false;
}

function periodShort(c) {
  if (!c.period) return "";
  if (monthly(c)) return D(c.period[0]).toLocaleDateString("es-ES", { month: "short", year: "numeric" });
  const my = (iso) => D(iso).toLocaleDateString("es-ES", { month: "short", year: "numeric" });
  return `${my(c.period[0])} – ${my(c.period[1])}`;
}

// Lo que va en la línea de la factura, como en la plantilla
function invoiceConcept(c) {
  if (!c.period) return c.concept;
  const p = monthly(c)
    ? `mes de ${monthText(c.period[0])}`
    : `del ${dmy(c.period[0])} al ${dmy(c.period[1])}`;
  return `${c.concept}\n(${p})`;
}

// En rojo lo que ya tocaba y no está pagado; lo demás, cuándo toca o cuándo se cobró
function status(c) {
  if (c.state === "paid") {
    const last = c.payments.map((p) => p.date).sort().pop();
    return [last ? `cobrado el ${fd(last)}` : "cobrado", "cb-ok"];
  }
  if (c.date > S.today) return [`le toca el ${fd(c.date)}`, ""];
  return [c.paid ? `ha pagado ${eur(c.paid)}, le queda ${eur(c.left)}` : `te debe desde el ${fd(c.date)}`, "cb-late"];
}

async function call(path, method = "POST", body) {
  try {
    const res = await api(`/api/cobros${path}`, { method, body });
    S = res;
    render();
    return res;
  } catch (e) {
    toast(e.message, true);
    return null;
  }
}

/* ---------- la vista: tres tarjetas ---------- */

const store = {  // lo que recuerda cada navegador (pestaña, rango, página de la tabla)
  get: (k, d) => { try { return localStorage.getItem(`cb-${k}`) || d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(`cb-${k}`, v); } catch { /* sin almacenamiento */ } },
};
let tab = store.get("tab", "sum");       // sum | cli | svc
let range = store.get("range", "month"); // month | year | all
let page = store.get("page", "loose");   // loose | <id de programa>
let moreMoves = false;

const empty = (t) => el("p", { class: "cb-empty" }, t);
const isOpen = (c) => c.state !== "paid" && c.date <= S.today;
const dmyShort = (iso) => D(iso).toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit", year: "2-digit" });
const loose = () => S.charges.filter((c) => !c.sub && c.left > 0);
const sum = (xs, f) => xs.reduce((t, x) => t + f(x), 0);
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// Una fila de lista: nombre, debajo el detalle, a la derecha el importe
function item(onclick, name, sub, right, cls = "", lead = null) {
  return el("button", { class: `cb-item ${cls}`, type: "button", onclick }, lead,
    el("span", { class: "cb-item-main" }, el("span", { class: "cb-item-name" }, name), sub ? el("span", { class: "cb-item-sub" }, sub) : null),
    right);
}

const amount = (n, cls = "") => el("b", { class: `mono cb-amt ${cls}` }, eur(n));

function render() {
  if (!S) return;
  paintCard();  // el widget de Estado usa los mismos datos: al volver, ya está al día
  renderHub();
  renderMoves();
  renderBoard();
}

/* Tarjeta 1: Resumen · Clientes · Servicios */

function renderHub() {
  for (const b of document.querySelectorAll("#cb-tabs .seg-btn")) b.classList.toggle("active", b.dataset.tab === tab);
  const add = $("cb-hub-add");
  const [label, fn] = { sum: ["+ Me deben", () => debtForm()], cli: ["+ Cliente", () => clientForm()], svc: ["+ Programa", () => productForm()] }[tab];
  add.textContent = label;
  add.onclick = fn;
  $("cb-hub").replaceChildren(...{ sum: hubSummary, cli: hubClients, svc: hubServices }[tab]());
}

function hubSummary() {
  const owed = S.charges.filter(isOpen).sort((a, b) => a.date.localeCompare(b.date));
  const next = S.upcoming;
  const col = (title, total, cls, rows, none) => el("div", { class: "cb-col" },
    el("div", { class: "cb-col-head" }, el("span", {}, title), amount(total, cls)),
    rows.length ? el("div", { class: "cb-list" }, ...rows) : el("p", { class: "cb-note cb-pad" }, none));
  return [el("div", { class: "cb-split" },
    col("Te deben", S.summary.owed, S.summary.owed ? "cb-late" : "", owed.map((c) =>
      item(() => payDialog(c.id), who(c), [dmyShort(c.date), short(c)].filter(Boolean).join(" · "), amount(c.left, "cb-late"))),
    "Nadie te debe nada 🎉"),
    col("Próximas deudas", sum(next, (x) => x.amount), "", next.map((x) =>
      item(() => (x.charge ? payDialog(x.charge) : x.sub ? subForm(x.client, S.subs.find((s) => s.id === x.sub)) : null),
        x.who, [dmyShort(x.date), x.concept].filter(Boolean).join(" · "), amount(x.amount))),
    "Nada a la vista."))];
}

// "MiERP · Básico" para una cuota; el concepto para lo demás
function short(c) {
  const { prod, plan } = planOf(subOf(c));
  return prod && plan ? `${prod.name} · ${plan.name}` : c.concept || "";
}

function hubClients() {
  if (!S.clients.length) return [empty("Aún no hay clientes. Créalos con «+ Cliente».")];
  return [el("div", { class: "cb-list" }, ...S.clients.slice().sort((a, b) => a.name.localeCompare(b.name, "es")).map((cl) => {
    const subs = S.subs.filter((s) => s.client === cl.id && S.status[s.id]?.state !== "end");
    const owes = sum(S.charges.filter((c) => c.client === cl.id && isOpen(c)), (c) => c.left);
    const what = subs.map((s) => { const { prod, plan } = planOf(s); return `${prod?.name} · ${plan?.name}`; });
    const jobs = S.charges.filter((c) => c.client === cl.id && !c.sub && c.left > 0).map((c) => c.concept);
    return item(() => openClient(cl.id), cl.name, [...what, ...jobs].join(" · ") || "sin suscripción",
      owes > 0 ? el("span", { class: "badge bad" }, `debe ${eur(owes)}`) : subs.length ? el("span", { class: "badge ok" }, "al día") : null,
      "", el("span", { class: "svc-icon cb-av" }, cl.name[0].toUpperCase()));
  }))];
}

function hubServices() {
  const debts = loose();
  const names = [...new Set(debts.map(who))];
  const rows = [item(() => goPage("loose"), "Deudas sueltas", names.join(", ") || "nadie te debe nada suelto",
    amount(sum(debts, (c) => c.left), debts.length ? "cb-late" : ""), page === "loose" ? "on" : "")];
  for (const p of S.products) {
    const subs = S.subs.filter((s) => s.product === p.id && S.status[s.id] && S.status[s.id].state !== "end");
    const late = subs.filter((s) => S.status[s.id].state === "late");
    const yearly = sum(subs, (s) => { const plan = p.plans.find((x) => x.id === s.plan); return plan ? (s.price ?? plan.price) * 12 / STEP[plan.period] : 0; });
    rows.push(item(() => goPage(p.id), p.name,
      subs.length ? subs.map((s) => client(s.client)?.name).join(", ") : "sin suscritos",
      el("span", { class: "cb-item-right" }, late.length ? el("span", { class: "badge bad" }, `${late.length} debe${late.length === 1 ? "" : "n"}`) : null,
        el("span", { class: "mono small muted" }, `${eur0(yearly)}/año`)), page === p.id ? "on" : ""));
  }
  if (!S.products.length) rows.push(el("p", { class: "cb-note cb-pad" }, "Añade tus programas con «+ Programa»: cada plan será una columna de la tabla de abajo."));
  return [el("div", { class: "cb-list" }, ...rows)];
}

/* Tarjeta 2: últimos movimientos */

function renderMoves() {
  for (const b of document.querySelectorAll("#cb-range .seg-btn")) b.classList.toggle("active", b.dataset.range === range);
  const y = S.today.slice(0, 4), m = S.today.slice(0, 7);
  const all = S.charges.flatMap((c) => c.payments.map((p) => ({ ...p, c })))
    .filter((p) => range === "all" || p.date.startsWith(range === "year" ? y : m))
    .sort((a, b) => b.date.localeCompare(a.date));
  const shown = moreMoves ? all : all.slice(0, 20);
  const when = { month: "este mes", year: `en ${y}`, all: "todavía" }[range];
  const label = { month: D(S.today).toLocaleDateString("es-ES", { month: "long" }), year: y, all: "desde el principio" }[range];
  $("cb-moves").replaceChildren(
    el("div", { class: "cb-col-head" }, el("span", {}, `Cobrado · ${label}`), amount(sum(all, (p) => p.amount), "cb-ok")),
    shown.length ? el("div", { class: "cb-list" }, ...shown.map((p) =>
    item(() => openCharge(p.c.id), who(p.c), `${dmyShort(p.date)} · ${short(p.c) || METHOD[p.method]}${p.c.invoice ? ` · ${p.c.invoice.number}` : ""}`,
      el("b", { class: "mono cb-amt cb-ok" }, `+${eur(p.amount)}`))),
  all.length > shown.length ? el("button", { class: "cb-more", type: "button", onclick: () => { moreMoves = true; renderMoves(); } }, `Ver ${all.length - shown.length} más`) : null)
    : empty(`Ningún cobro ${when}.`));
}

/* Tarjeta 3: la tabla (deudas sueltas o un programa con una columna por plan) */

const pages = () => ["loose", ...S.products.map((p) => p.id)];

function goPage(p, scroll = true) {
  page = p;
  store.set("page", p);
  renderHub();
  renderBoard();
  if (scroll && matchMedia("(max-width: 900px)").matches) document.querySelector(".cb-board").scrollIntoView({ behavior: "smooth", block: "start" });
}

function step(dir) {
  const ps = pages();
  goPage(ps[(ps.indexOf(page) + dir + ps.length) % ps.length], false);
}

function renderBoard() {
  const ps = pages();
  if (!ps.includes(page)) page = "loose";
  $("cb-pos").textContent = `${ps.indexOf(page) + 1}/${ps.length}`;
  $("cb-prev").disabled = $("cb-next").disabled = ps.length < 2;
  const prod = S.products.find((p) => p.id === page);
  if (!prod) return boardLoose();
  const subs = S.subs.filter((s) => s.product === prod.id && S.status[s.id]);
  const live = subs.filter((s) => S.status[s.id].state !== "end");
  $("cb-board-title").textContent = prod.name;
  $("cb-board-sub").textContent = `${plural(live.length, "suscrito")}${subs.length > live.length ? ` · ${subs.length - live.length} de baja` : ""}`;
  $("cb-board-tool").replaceChildren(btn("Editar planes", () => productForm(prod), "btn-sm"));
  $("cb-board").replaceChildren(prod.plans.length ? el("div", { class: "cb-plans" }, ...prod.plans.map((plan) => planColumn(prod, plan, live)))
    : empty("Este programa aún no tiene planes: añádelos en «Editar planes»."));
}

function planColumn(prod, plan, live) {
  const subs = live.filter((s) => s.plan === plan.id)
    .sort((a, b) => (S.status[b.id].state === "late") - (S.status[a.id].state === "late") || (S.status[a.id].next || "").localeCompare(S.status[b.id].next || ""));
  return el("section", { class: "cb-plancol" },
    el("header", { class: "cb-plancol-head" },
      el("span", { class: "cb-plan-name" }, plan.name),
      el("span", { class: "mono small muted" }, `${eur0(plan.price)}${plan.period === "year" ? "" : ` ${PERIOD[plan.period][1]}`}`),
      el("button", { class: "cb-plus", type: "button", title: `Suscribir a alguien al plan ${plan.name}`, onclick: () => addToPlan(prod, plan) }, "+")),
    subs.length ? el("div", { class: "cb-subs" }, ...subs.map(subRow)) : el("p", { class: "cb-note cb-pad" }, "Nadie todavía. Pulsa + para añadir a alguien."));
}

function subRow(s) {
  const st = S.status[s.id];
  const cl = client(s.client);
  const cs = S.charges.filter((c) => c.sub === s.id);
  const lastPaid = cs.filter((c) => c.state === "paid").at(-1);
  const anyInv = cs.filter((c) => c.invoice).at(-1);
  let inv;
  if (lastPaid && !lastPaid.invoice) inv = btn("Factura", () => invoiceForm(lastPaid.id), "btn-sm cb-mark");
  else if ((lastPaid || anyInv)?.invoice) {
    const c = lastPaid?.invoice ? lastPaid : anyInv;
    inv = S.template ? el("a", { class: "btn btn-sm", href: `/api/cobros/charges/${c.id}/factura.xlsx`, download: "", title: `Descargar la factura ${c.invoice.number}` }, "Factura")
      : btn("Factura", () => openTemplate(() => openCharge(c.id)), "btn-sm");
  } else inv = el("button", { class: "btn btn-sm", type: "button", disabled: true, title: "Aún no ha pagado nada que facturar" }, "Factura");
  const late = st.state === "late";
  const free = s.free_until && s.free_until > S.today;
  return el("div", { class: `cb-sub ${late ? "late" : "ok"}` },
    el("button", { class: "cb-sub-main", type: "button", title: late ? "Apuntar el pago" : "Ver sus cobros",
      onclick: () => (st.charge ? payDialog(st.charge) : cs.length ? openCharge(cs.at(-1).id) : subForm(s.client, s)) },
    el("span", { class: "cb-item-name" }, cl.name),
    el("span", { class: `mono cb-date ${late ? "cb-late" : "cb-ok"}`, title: late ? `Debe ${eur(st.amount)} desde el ${fd(st.next)}` : `Próximo pago: ${fd(st.next)}` },
      st.next ? dmyShort(st.next) : "—"),
    free || s.price != null ? el("span", { class: "cb-item-sub" }, [free ? `gratis hasta ${dmyShort(s.free_until)}` : null, s.price != null ? `precio ${eur(s.price)}` : null].filter(Boolean).join(" · ")) : null),
    el("span", { class: "cb-sub-act" }, inv, btn("Editar", () => subForm(s.client, s, null, closeSheet), "btn-sm")));
}

function boardLoose() {
  const debts = loose().sort((a, b) => a.date.localeCompare(b.date));
  $("cb-board-title").textContent = "Deudas sueltas";
  $("cb-board-sub").textContent = debts.length ? `${plural(new Set(debts.map(who)).size, "persona")} · ${eur(sum(debts, (c) => c.left))}` : "lo que te deben fuera de las suscripciones";
  $("cb-board-tool").replaceChildren(btn("+ Apuntar", () => debtForm(), "btn-sm"));
  $("cb-board").replaceChildren(debts.length ? el("div", { class: "cb-table" }, ...debts.map((c) => {
    const future = c.date > S.today;
    return el("button", { class: `cb-trow ${future ? "" : "late"}`, type: "button", onclick: () => payDialog(c.id) },
      el("span", { class: "cb-item-name" }, who(c)),
      el("span", { class: "cb-trow-what" }, c.concept || "—", c.client ? el("span", { class: "cb-tag" }, c.invoice ? c.invoice.number : "cliente") : null),
      el("span", { class: `mono small ${future ? "muted" : "cb-late"}` }, dmyShort(c.date)),
      el("span", { class: "cb-trow-amt" }, amount(c.left, future ? "" : "cb-late"), c.paid ? el("span", { class: "small muted" }, `pagado ${eur(c.paid)} de ${eur(c.total)}`) : null),
      c.paid ? el("span", { class: "cb-trow-note small muted" }, `ha pagado ${eur(c.paid)} de ${eur(c.total)}`) : null);
  })) : empty("Nadie te debe nada suelto 🎉"));
}

function addToPlan(prod, plan) {
  subForm(null, null, { product: prod.id, plan: plan.id }, closeSheet);
}

async function load() {
  try {
    S = await api("/api/cobros");
    render();
  } catch (e) {
    if (e.message !== "no autenticado") $("cb-hub").replaceChildren(empty(`No se pudo cargar: ${e.message}`));
  }
}

/* ---------- ¿ya te lo ha pagado? ---------- */

const METHOD = Object.fromEntries(METHODS);

function payDialog(id) {
  const c = charge(id);
  if (!c) return closeSheet();
  if (c.left <= 0) return openCharge(id);
  const method = chips(METHODS, c.payments.at(-1)?.method || store.get("method", c.client ? "transferencia" : "bizum"));
  const when = input({ type: "date", value: S.today });
  const part = money(Math.round(c.left * 50) / 100);
  const full = btn(`Sí, pagado (${eur(c.left)})`, () => pay(c.left), "btn-primary");
  const savePart = btn("Apuntar esta parte", () => pay(num(part.value)), "btn-primary");
  const partBox = el("div", { class: "form", hidden: true },
    el("div", { class: "cb-two" }, field("Cuánto te ha pagado", part), el("div", { class: "chips cb-chips-end" },
      el("button", { type: "button", onclick: () => { part.value = dec(Math.round(c.left * 50) / 100); } }, "La mitad"))),
    savePart);
  let busy = false;
  const pay = async (n) => {
    if (busy) return;  // un doble toque con la red lenta no apunta el cobro dos veces
    if (!(n > 0)) return toast("¿Cuánto te ha pagado?", true);
    store.set("method", method.get());
    busy = full.disabled = savePart.disabled = true;
    try {
      if (!await call(`/charges/${id}/pay`, "POST", { amount: n, method: method.get(), date: when.value })) return;
    } finally {
      busy = full.disabled = savePart.disabled = false;
    }
    const after = charge(id);
    if (after.left > 0) { toast(`Apuntado: quedan ${eur(after.left)}`); return payDialog(id); }
    toast(`Cobrado ${eur(after.total)} ✓`);
    if (after.invoice && !c.invoice) return invoiceDone(id);
    closeSheet();
  };
  sheet(who(c), [short(c), c.period ? periodShort(c) : null].filter(Boolean).join(" · "),
    el("div", { class: "cb-total" }, el("span", { class: c.date <= S.today ? "cb-late" : "muted" },
      c.date <= S.today ? (c.paid ? `Le queda por pagar` : `Te debe desde el ${fd(c.date)}`) : `Le toca el ${fd(c.date)}`), el("b", {}, eur(c.left))),
    el("h3", { class: "section-title" }, "¿Ya te lo ha pagado?"),
    el("div", { class: "form" },
      el("div", { class: "cb-two" }, field("Cómo", method.box), field("Cuándo", when)),
      el("div", { class: "btn-row" },
        full,
        btn("Solo una parte", (e) => { partBox.hidden = !partBox.hidden; e.currentTarget.hidden = true; part.select(); })),
      partBox),
    el("div", { class: "btn-row cb-sheet-foot" },
      btn("Ver detalle", () => openCharge(id), "btn-sm"),
      c.client ? btn("Ver cliente", () => openClient(c.client), "btn-sm") : btn("Editar", () => debtForm(c), "btn-sm")));
}

// Al cobrar del todo, el servidor ya ha hecho la factura (y la ha guardado en la carpeta)
function invoiceDone(id) {
  const c = charge(id);
  sheet(`Factura ${c.invoice.number} hecha ✓`, `${who(c)} · ${eur(c.total)} · ${PAID_AS[c.payments.at(-1)?.method] || "Pagada"}`,
    el("p", { class: "cb-note" }, S.template
      ? "Está guardada en la carpeta de facturas. Descárgala, revísala y expórtala a PDF para enviarla."
      : "Está apuntada, pero aún no has subido tu plantilla: súbela para tener el archivo."),
    el("div", { class: "btn-row" },
      S.template ? el("a", { class: "btn btn-primary", href: `/api/cobros/charges/${id}/factura.xlsx`, download: "" }, "Descargar")
        : btn("Subir plantilla", () => openTemplate(() => invoiceDone(id)), "btn-primary"),
      btn("Cambiar", () => invoiceForm(id)),
      btn("Cerrar", () => closeSheet())));
}

/* ---------- apunte rápido: alguien te debe algo ---------- */

function debtForm(c) {
  const editing = !!c;
  c = c || { who: "", concept: "", base: null, date: S.today };
  const names = [...new Set(S.charges.filter((x) => !x.client).map((x) => x.who))].sort((a, b) => a.localeCompare(b, "es"));
  const list = el("datalist", { id: "cb-names" }, ...names.map((n) => el("option", { value: n })));
  const name = input({ value: c.who, required: true, placeholder: "Nombre", maxlength: 120, list: "cb-names" });
  const concept = input({ value: c.concept, placeholder: "Cena, entradas… (opcional)", maxlength: 300 });
  const base = money(c.base, { required: true });
  const date = input({ type: "date", value: c.date, required: true });
  sheet(editing ? "Editar deuda" : "Te deben", "sin factura: un amigo, un préstamo…",
    form(async () => {
      const res = await call("/charges", "POST", { id: c.id, client: null, who: name.value, concept: concept.value, base: num(base.value), taxes: false, date: date.value, notes: c.notes || "" });
      if (res) { toast("Apuntado"); closeSheet(); if (!editing) goPage("loose", false); }
    },
    list, field("Quién", name), field("Concepto", concept),
    el("div", { class: "cb-two" }, field("Cuánto", base), field("Desde", date)),
    el("p", { class: "cb-note" }, "Si es a un cliente con factura (una web, una instalación…), apúntalo desde su ficha: «Clientes» → el cliente → «+ Cargo o encargo»."),
    submit(editing ? "Guardar" : "Apuntar"),
    editing ? btn("Borrar", async () => {
      if (!confirm(`¿Borrar lo que te debe ${c.who}?`)) return;
      if (await call(`/charges/${c.id}`, "DELETE")) { toast("Borrado"); closeSheet(); }
    }, "btn-danger") : null));
  (editing ? base : name).focus();
}

/* ---------- piezas de formulario ---------- */

function chips(options, initial, onchange) {
  let value = initial;
  const box = el("div", { class: "chips" });
  const draw = () => box.replaceChildren(...options.map(([v, label]) =>
    el("button", { type: "button", class: v === value ? "on" : "", onclick: () => { value = v; draw(); onchange?.(v); } }, label)));
  draw();
  return { box, get: () => value, set: (v) => { value = v; draw(); } };
}

const input = (attrs) => el("input", { autocomplete: "off", ...attrs });
const money = (value, attrs = {}) => input({ inputmode: "decimal", value: dec(value), placeholder: "0,00", ...attrs });
const field = (label, ...x) => el("label", {}, label, ...x);
const kv = (...pairs) => el("dl", { class: "cb-kv" }, ...pairs.filter((p) => p && p[1] != null && p[1] !== "").map(([k, v, cls]) => [el("dt", {}, k), el("dd", { class: cls || "" }, v)]));

function form(onsubmit, ...children) {
  const go = children.find((c) => c?.type === "submit");
  return el("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    if (go) go.disabled = true;
    try { await onsubmit(); } finally { if (go) go.disabled = false; }
  } }, ...children);
}

const submit = (t) => el("button", { class: "btn btn-primary", type: "submit" }, t);
const btn = (t, onclick, cls = "") => el("button", { class: `btn ${cls}`, type: "button", onclick }, t);

/* ---------- un cargo ---------- */

function openCharge(id) {
  const c = charge(id);
  if (!c) return closeSheet();
  const [st, cls] = status(c);
  const cl = client(c.client);

  const pay = c.left > 0 ? [el("div", { class: "btn-row" }, btn("Apuntar cobro", () => payDialog(id), "btn-primary"))] : [];

  const inv = c.invoice;
  const invoice = [el("h3", { class: "section-title" }, "Factura"),
    inv ? kv(["Número", inv.number, "mono"], ["Fecha", fd(inv.date)]) : el("p", { class: "cb-note" },
      c.client ? "Aún sin factura. Hazla cuando te paguen (o antes, si te la piden)." : "Es un apunte suelto: sin factura."),
    el("div", { class: "btn-row" },
      inv && S.template ? el("a", { class: "btn btn-primary", href: `/api/cobros/charges/${id}/factura.xlsx`, download: "" }, "Descargar (.xlsx)") : null,
      inv ? btn("Cambiar", () => invoiceForm(id)) : c.client ? btn("Hacer factura", () => invoiceForm(id), "btn-primary") : null,
      inv ? btn("Quitar", async () => {
        if (!confirm(`¿Quitar la factura ${inv.number}? Su número queda anulado. Si ya la enviaste, haz una rectificativa.`)) return;
        if (await call(`/charges/${id}/invoice`, "DELETE")) openCharge(id);
      }) : null)];

  sheet(who(c), shortConcept(c) + (c.period ? ` · ${periodShort(c)}` : ""),
    el("div", { class: "cb-total" }, el("span", { class: cls }, c.state === "paid" ? "Cobrado ✓" : st),
      el("b", {}, c.state === "paid" ? eur(c.total) : eur(c.left))),
    kv(["Concepto", c.concept], c.period ? ["Periodo", `${fd(c.period[0])} – ${fd(c.period[1])}`] : null,
      ["Fecha", fd(c.date)],
      ["Importe", c.iva || c.irpf ? `${eur(c.base)} + IVA ${dec(c.iva)} %${c.irpf ? ` − IRPF ${dec(c.irpf)} %` : ""}` : eur(c.base)],
      ["Total", eur(c.total), "mono"], c.paid ? ["Cobrado", eur(c.paid), "mono"] : null,
      cl ? ["Cliente", cl.name] : null, c.notes ? ["Notas", c.notes] : null),
    c.payments.length ? [el("h3", { class: "section-title" }, "Cobros"), el("ul", { class: "cb-rows" }, ...c.payments.map((p, i) => el("li", {},
      el("span", {}, `${fd(p.date)} · ${METHODS.find((m) => m[0] === p.method)?.[1] || p.method}`),
      el("b", { class: "mono" }, eur(p.amount)),
      el("button", { class: "x", type: "button", title: "Borrar este cobro", onclick: async () => {
        const undo = inv?.auto && round2(c.left + p.amount) > 0;  // deja de estar pagado: su factura automática se va
        if (!confirm(`¿Borrar el cobro de ${eur(p.amount)} del ${fd(p.date)}?${undo ? ` Se quitará también la factura ${inv.number}; recuperará ese número cuando vuelva a estar pagado. Si ya la enviaste, haz una rectificativa.` : ""}`)) return;
        if (await call(`/charges/${id}/pay/${i}`, "DELETE")) openCharge(id);
      } }, "✕"))))] : null,
    ...pay, ...invoice,
    el("div", { class: "btn-row" },
      cl ? btn("Ver cliente", () => openClient(cl.id)) : null,
      btn("Editar", () => (c.client || c.sub ? chargeForm(c) : debtForm(c))),
      btn("Borrar", async () => {
        if (!confirm(`¿Borrar «${c.concept}» de ${who(c)}?${c.sub ? " No volverá a salir para este periodo." : ""}`)) return;
        if (await call(`/charges/${id}`, "DELETE")) { toast("Borrado"); closeSheet(); }
      }, "btn-danger")));
}

function chargeForm(c, clientId, whoName) {
  const editing = !!c;
  c = c || { client: clientId ?? null, who: whoName || "", concept: "", base: null, date: S.today, due: null, notes: "" };
  const OTHER = "";
  const pick = el("select", {}, el("option", { value: OTHER }, "Otra persona (apunte suelto)"),
    ...S.clients.slice().sort((a, b) => a.name.localeCompare(b.name, "es")).map((x) => el("option", { value: x.id, selected: x.id === c.client }, x.name)));
  if (!c.client) pick.value = OTHER;
  const whoIn = input({ value: c.who, placeholder: "Nombre", maxlength: 120 });
  const concept = input({ value: c.concept, required: true, placeholder: "p. ej. Página web (50 % al empezar)", maxlength: 300 });
  const base = money(c.base, { required: true });
  const taxes = el("input", { type: "checkbox", checked: editing ? c.taxes : !!c.client });
  const date = input({ type: "date", value: c.date, required: true });
  const notes = el("textarea", { maxlength: 2000, placeholder: "opcional" }, c.notes || "");
  const preview = el("p", { class: "cb-note" });
  const whoRow = field("Quién", whoIn);
  const locked = editing && c.invoice;
  // Al editar, sus tipos se quedan; si no los tenía o cambia de cliente, los de ahora
  const rates = () => {
    const cl = client(pick.value);
    return { iva: editing && c.taxes ? c.iva : S.settings.iva,
      irpf: editing && c.taxes && c.client === (cl ? cl.id : null) ? c.irpf : cl ? cl.irpf : 0 };
  };
  const sync = () => {
    whoRow.hidden = !!client(pick.value);
    const b = num(base.value) || 0;
    const { iva, irpf } = rates();
    preview.textContent = taxes.checked
      ? `Te pagarán ${eur(totalOf(b, iva, irpf))} (${eur(b)} + IVA ${dec(iva)} %${irpf ? ` − IRPF ${dec(irpf)} %` : ""}).`
      : `Te deben ${eur(b)}, sin IVA ni factura.`;
  };
  pick.onchange = () => { taxes.checked = !!client(pick.value); sync(); };
  base.oninput = taxes.onchange = sync;
  sync();
  sheet(editing ? "Editar" : "Nuevo cargo", editing ? who(c) : "un encargo, una instalación, algo que te deben…",
    form(async () => {
      const cl = client(pick.value);
      const body = { id: c.id, client: cl ? cl.id : null, who: cl ? "" : whoIn.value, concept: concept.value,
        base: num(base.value), date: date.value, due: c.due || null, notes: notes.value };
      if (!locked) { body.taxes = taxes.checked; if (taxes.checked) Object.assign(body, rates()); }
      const res = await call("/charges", "POST", body);
      if (res) { toast("Guardado"); openCharge(res.saved); }
    },
    field("Cliente", pick), whoRow,
    field("Concepto", concept),
    el("div", { class: "cb-two" }, field(taxes.checked ? "Importe sin IVA" : "Importe", base), field("Fecha", date)),
    el("label", { class: "cb-check" }, taxes, "Con IVA y retención (lleva factura)"),
    preview,
    field("Notas", notes),
    locked ? el("p", { class: "cb-note" }, "Tiene factura: el cliente, el importe y los impuestos salen de ella (cámbiala desde «Factura»).") : null,
    el("p", { class: "cb-note" }, "Para un pago a plazos, pon el total y ve apuntando cada cobro (hay un botón «La mitad»)."),
    submit("Guardar")));
  if (locked) { pick.disabled = true; base.disabled = true; taxes.disabled = true; }
  (editing ? concept : pick).focus();
}

/* ---------- factura ---------- */

function invoiceForm(id) {
  const c = charge(id);
  const cl = client(c.client);
  const inv = c.invoice || { number: S.next_number, date: S.today, lines: [{ concept: invoiceConcept(c), qty: 1, price: c.base }],
    pay_text: c.state === "paid" && c.payments.length ? PAID_AS[c.payments.at(-1).method]
      : S.settings.iban ? `Transferencia bancaria a la cuenta ${S.settings.iban}` : "" };
  const number = input({ value: inv.number, required: true, class: "mono" });
  const date = input({ type: "date", value: inv.date, required: true });
  const iva = money(c.taxes ? c.iva : S.settings.iva);
  const irpf = money(c.taxes ? c.irpf : cl?.irpf ?? 0);
  const payText = input({ value: inv.pay_text || "", placeholder: "Forma de pago" });
  const lines = el("div", { class: "form" });
  const totalBox = el("div", { class: "cb-total" });
  const rows = [];
  const recalc = () => {
    const base = rows.reduce((t, r) => t + round2((num(r.qty.value) || 0) * (num(r.price.value) || 0)), 0);
    const i = num(iva.value) || 0, r = num(irpf.value) || 0;
    totalBox.replaceChildren(el("span", { class: "muted" }, `${eur(base)} + IVA ${eur(pct(base, i))}${r ? ` − IRPF ${eur(pct(base, r))}` : ""}`), el("b", {}, eur(totalOf(base, i, r))));
  };
  const addLine = (ln) => {
    if (rows.length >= 4) return toast("En la plantilla caben 4 líneas", true);
    const r = { concept: el("textarea", { rows: 2, placeholder: "Concepto" }, ln.concept || ""), qty: money(ln.qty ?? 1, { "aria-label": "Cantidad" }), price: money(ln.price, { "aria-label": "Precio sin IVA" }) };
    r.row = el("div", { class: "cb-line" }, r.concept, r.qty, r.price, el("button", { class: "x", type: "button", title: "Quitar línea", onclick: () => {
      if (rows.length === 1) return;
      rows.splice(rows.indexOf(r), 1); r.row.remove(); recalc();
    } }, "✕"));
    r.qty.oninput = r.price.oninput = recalc;
    rows.push(r);
    lines.append(r.row);
    recalc();
  };
  inv.lines.forEach(addLine);
  iva.oninput = irpf.oninput = recalc;
  sheet(c.invoice ? `Factura ${c.invoice.number}` : "Hacer factura", cl ? `${cl.name}${cl.nif ? ` · ${cl.nif}` : ""}` : who(c),
    form(async () => {
      const body = { number: number.value, date: date.value, iva: num(iva.value), irpf: num(irpf.value), pay_text: payText.value,
        lines: rows.map((r) => ({ concept: r.concept.value, qty: num(r.qty.value), price: num(r.price.value) })) };
      if (!await call(`/charges/${id}/invoice`, "POST", body)) return;
      openCharge(id);
      if (S.template) {
        el("a", { href: `/api/cobros/charges/${id}/factura.xlsx`, download: "" }).click();
        toast("Factura guardada: ábrela, revísala y expórtala a PDF");
      } else toast("Factura apuntada. Sube tu plantilla para guardarla y descargarla");
    },
    el("div", { class: "cb-two" }, field("Número", number), field("Fecha", date)),
    field("Líneas (cantidad y precio sin IVA)", lines),
    btn("+ Línea", () => addLine({ concept: "", qty: 1, price: null })),
    el("div", { class: "cb-two" }, field("IVA %", iva), field("Retención IRPF %", irpf)),
    field("Forma de pago", payText),
    totalBox,
    !cl?.nif ? el("p", { class: "cb-note cb-soon" }, "Este cliente no tiene NIF: para una factura completa hace falta (edita el cliente).") : null,
    S.template ? el("p", { class: "cb-note" }, "Se rellena una copia de tu plantilla y se guarda en la carpeta de facturas. Ábrela, revísala y expórtala a PDF para enviarla. ",
      el("button", { class: "cb-link", type: "button", onclick: () => openTemplate(() => invoiceForm(id)) }, "Cambiar plantilla"))
      : el("p", { class: "cb-note cb-soon" }, "Aún no has subido tu plantilla (.xlsx): sin ella la factura se apunta pero no se puede descargar. ",
        el("button", { class: "cb-link", type: "button", onclick: () => openTemplate(() => invoiceForm(id)) }, "Subirla")),
    submit(S.template ? "Guardar y descargar" : "Guardar")));
  if (!c.invoice) number.select();
}

function openTemplate(back) {
  const file = el("input", { type: "file", accept: ".xlsx", hidden: true, onchange: async () => {
    const f = file.files[0];
    if (!f) return;
    try {
      const r = await fetch("/api/cobros/plantilla.xlsx", { method: "PUT", body: f, credentials: "same-origin" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `error ${r.status}`);
      toast("Plantilla subida ✓");
      await load();
      (back || openTemplate)();
    } catch (e) { toast(e.message, true); }
  } });
  sheet("Plantilla de factura", S.template ? "subida" : "sin subir",
    el("p", { class: "cb-note" }, "Tu .xlsx con las pestañas «Factura» e «Instrucciones». Al hacer una factura se rellena una copia con el número, la fecha, el cliente, las líneas, la forma de pago y los tipos de IVA y retención; lo demás (tus datos, el diseño) se queda como lo tengas."),
    el("p", { class: "cb-note" }, "No cambies de sitio esas celdas (D1, D2, A12–A15, A18–C21, A30 e Instrucciones B15–B16)."),
    el("p", { class: "cb-note" }, "Cada factura que hagas se guarda ya rellena en ", el("span", { class: "mono" }, S.folder), " (una carpeta por año). Cambiar la plantilla no toca las ya hechas."),
    S.annulled.length ? [el("h3", { class: "section-title" }, "Números anulados"), el("ul", { class: "cb-rows" }, ...S.annulled.map((a) => el("li", {},
      el("span", {}, `${a.client} · quitada el ${fd(a.removed)}`), el("b", { class: "mono" }, a.number))))] : null,
    file,
    el("div", { class: "btn-row" },
      btn(S.template ? "Cambiar plantilla" : "Subir plantilla", () => file.click(), "btn-primary"),
      S.template ? el("a", { class: "btn", href: "/api/cobros/plantilla.xlsx", download: "" }, "Descargar la actual") : null,
      back ? btn("Volver", back) : null));
}

/* ---------- clientes ---------- */

function openClient(id) {
  const c = client(id);
  if (!c) return closeSheet();
  const subs = S.subs.filter((s) => s.client === id);
  const charges = S.charges.filter((x) => x.client === id);
  const open = charges.filter((x) => x.state !== "paid");
  const owes = open.filter((x) => x.date <= S.today).reduce((t, x) => t + x.left, 0);
  const done = charges.filter((x) => x.state === "paid").reverse().slice(0, 8);
  const chargeLine = (x) => { const [st, cls] = status(x); return el("li", {}, el("button", { class: "cb-go", type: "button", onclick: () => openCharge(x.id) },
    el("div", {}, `${shortConcept(x)}${x.period ? ` · ${periodShort(x)}` : ""}`), el("div", { class: `small ${cls || "muted"}` }, st)),
  el("b", { class: "mono" }, eur(x.state === "paid" ? x.total : x.left))); };
  sheet(c.name, c.nif || "sin NIF",
    el("div", { class: "cb-total" }, el("span", {}, owes > 0 ? "Te debe" : "Al día"), el("b", {}, eur(owes))),
    kv(["NIF", c.nif], ["Dirección", [c.address, c.city].filter(Boolean).join("\n")], ["Email", c.email], ["Teléfono", c.phone],
      ["Retención", c.irpf ? `IRPF ${dec(c.irpf)} %` : "sin retención (particular)"], ["Notas", c.notes]),
    el("h3", { class: "section-title" }, "Suscripciones"),
    subs.length ? el("ul", { class: "cb-rows" }, ...subs.map((s) => {
      const { prod, plan } = planOf(s);
      const price = s.price ?? plan?.price;
      const ended = s.end && s.end <= S.today;
      const bits = [`primera cuota ${fd(s.start)}`, s.free_until && s.free_until > S.today ? `gratis hasta ${fd(s.free_until)}` : null,
        s.end ? `${ended ? "de baja desde" : "baja el"} ${fd(s.end)}` : null].filter(Boolean);
      return el("li", {}, el("button", { class: "cb-go", type: "button", onclick: () => subForm(id, s) },
        el("div", { class: ended ? "muted" : "" }, `${prod?.name || "?"} · ${plan?.name || "?"}`),
        el("div", { class: "small muted" }, bits.join(" · "))),
      el("b", { class: "mono" }, `${eur(price)}${plan ? ` ${PERIOD[plan.period][1]}` : ""}`));
    })) : el("p", { class: "cb-note" }, "Sin suscripciones."),
    el("div", { class: "btn-row" }, btn("+ Suscripción", () => subForm(id)), btn("+ Cargo o encargo", () => chargeForm(null, id))),
    open.length ? [el("h3", { class: "section-title" }, "Pendiente"), el("ul", { class: "cb-rows" }, ...open.map(chargeLine))] : null,
    done.length ? [el("h3", { class: "section-title" }, "Últimos cobros"), el("ul", { class: "cb-rows" }, ...done.map(chargeLine))] : null,
    el("div", { class: "btn-row" },
      btn("Editar", () => clientForm(c)),
      btn("Borrar", async () => {
        if (!confirm(`¿Borrar a ${c.name}, sus suscripciones y lo que tenga apuntado? No se puede deshacer.`)) return;
        if (await call(`/clients/${id}`, "DELETE")) { toast("Cliente borrado"); closeSheet(); }
      }, "btn-danger")));
}

function clientForm(c) {
  const editing = !!c;
  c = c || { name: "", nif: "", address: "", city: "", email: "", phone: "", irpf: S.settings.irpf, notes: "" };
  const opts = [...new Set([S.settings.irpf, 15, 7, 0])].map((v) => [v, v ? `${dec(v)} %` : "0 % (particular)"]);
  if (!opts.some(([v]) => v === c.irpf)) opts.push([c.irpf, `${dec(c.irpf)} %`]);
  const irpf = chips(opts, c.irpf);
  const f = {
    name: input({ value: c.name, required: true, placeholder: "Nombre o razón social", maxlength: 120 }),
    nif: input({ value: c.nif, placeholder: "12345678Z / B12345678", maxlength: 20, autocapitalize: "characters" }),
    address: input({ value: c.address, placeholder: "Calle y número", maxlength: 120 }),
    city: input({ value: c.city, placeholder: "28001 Madrid", maxlength: 120 }),
    email: input({ value: c.email, type: "email", maxlength: 120 }),
    phone: input({ value: c.phone, type: "tel", maxlength: 40 }),
  };
  const notes = el("textarea", { maxlength: 2000, placeholder: "opcional" }, c.notes || "");
  sheet(editing ? `Editar ${c.name}` : "Nuevo cliente", "lo que sale en sus facturas",
    form(async () => {
      const res = await call("/clients", "POST", { id: c.id, ...Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.value])), irpf: irpf.get(), notes: notes.value });
      if (res) { toast("Guardado"); openClient(res.saved); }
    },
    field("Nombre", f.name), field("NIF", f.nif), field("Dirección", f.address), field("CP y ciudad", f.city),
    el("div", { class: "cb-two" }, field("Email", f.email), field("Teléfono", f.phone)),
    field("Retención de IRPF", irpf.box, el("span", { class: "help" }, "Si es empresa o autónomo, la tuya; si es un particular, 0.")),
    field("Notas", notes),
    submit(editing ? "Guardar" : "Crear cliente")));
  f.name.focus();
}

function subForm(clientId, s, preset, back) {
  if (!S.products.some((p) => p.plans.length)) {
    toast("Primero añade un programa con sus planes", true);
    return productForm();
  }
  const editing = !!s;
  s = s || { client: clientId, product: preset?.product ?? S.products.find((p) => p.plans.length).id, plan: preset?.plan ?? null, price: null, start: S.today, free_until: null, end: null, notes: "" };
  const NEW = "__new";
  const who = el("select", { required: true },
    ...S.clients.slice().sort((a, b) => a.name.localeCompare(b.name, "es")).map((c) => el("option", { value: c.id, selected: c.id === s.client }, c.name)),
    el("option", { value: NEW }, "+ Nuevo cliente…"));
  // el cliente nuevo se crea a la vez que la suscripción (lo demás, en su ficha)
  const nc = {
    name: input({ placeholder: "Nombre o razón social", maxlength: 120 }),
    nif: input({ placeholder: "12345678Z / B12345678", maxlength: 20, autocapitalize: "characters" }),
    address: input({ placeholder: "Calle y número", maxlength: 120 }),
    city: input({ placeholder: "28001 Madrid", maxlength: 120 }),
  };
  const ncIrpf = chips([...new Set([S.settings.irpf, 0])].map((v) => [v, v ? `${dec(v)} % (empresa o autónomo)` : "0 % (particular)"]), S.settings.irpf);
  const newBox = el("div", { class: "form cb-newclient", hidden: true },
    field("Nombre", nc.name), field("NIF", nc.nif), field("Dirección", nc.address), field("CP y ciudad", nc.city),
    field("Retención de IRPF", ncIrpf.box));
  who.onchange = () => {
    newBox.hidden = who.value !== NEW;
    nc.name.required = !newBox.hidden;
    if (!newBox.hidden) nc.name.focus();
  };
  const prod = el("select", {}, ...S.products.filter((p) => p.plans.length).map((p) => el("option", { value: p.id, selected: p.id === s.product }, p.name)));
  const plan = el("select", {});
  const price = money(s.price);
  const start = input({ type: "date", value: s.start, required: true });
  const free = input({ type: "date", value: s.free_until || "" });
  const end = input({ type: "date", value: s.end || "" });
  const notes = el("textarea", { maxlength: 2000, placeholder: "opcional" }, s.notes || "");
  const info = el("p", { class: "cb-note" });
  const fillPlans = () => {
    const p = S.products.find((x) => x.id === prod.value);
    plan.replaceChildren(...p.plans.map((x) => el("option", { value: x.id, selected: x.id === s.plan }, `${x.name} · ${eur(x.price)} ${PERIOD[x.period][1]}`)));
    explain();
  };
  const explain = () => {
    const p = S.products.find((x) => x.id === prod.value)?.plans.find((x) => x.id === plan.value);
    if (!p) return;
    price.placeholder = dec(p.price);
    info.textContent = `Sale una cuota ${PERIOD[p.period][0].toLowerCase()} desde el ${start.value ? fd(start.value) : "…"}`
      + (free.value ? `, sin cobrar las de antes del ${fd(free.value)}` : "") + (end.value ? ` y hasta el ${fd(end.value)}` : "")
      + `. Aparece ${S.settings.lead_days ?? 7} días antes para que puedas cobrarla por adelantado.`;
  };
  prod.onchange = fillPlans;
  plan.onchange = start.oninput = free.oninput = end.oninput = explain;
  fillPlans();
  const cname = S.clients.find((c) => c.id === s.client)?.name;
  sheet(editing ? "Editar suscripción" : "Nueva suscripción", cname || "",
    form(async () => {
      if (who.value === NEW) {
        const made = await call("/clients", "POST", { ...Object.fromEntries(Object.entries(nc).map(([k, v]) => [k, v.value])), irpf: ncIrpf.get() });
        if (!made) return;
        who.replaceChildren(el("option", { value: made.saved }, nc.name.value));
        who.value = made.saved;
        newBox.hidden = true;
      }
      const res = await call("/subs", "POST", { id: s.id, client: who.value, product: prod.value, plan: plan.value,
        price: price.value.trim() ? num(price.value) : null, start: start.value, free_until: free.value || null, end: end.value || null, notes: notes.value });
      if (res) { toast("Guardada"); (back || (() => openClient(who.value)))(); }
    },
    clientId ? null : [field("Cliente", who), newBox],
    el("div", { class: "cb-two" }, field("Programa", prod), field("Plan", plan)),
    field("Precio para este cliente (sin IVA)", price, el("span", { class: "help" }, "Vacío: el del plan.")),
    field("Primera cuota", start),
    el("div", { class: "cb-two" }, field("Gratis hasta (opcional)", free), field("Baja (opcional)", end)),
    info,
    field("Notas", notes),
    submit(editing ? "Guardar" : "Añadir"),
    editing ? btn("Borrar suscripción", async () => {
      if (!confirm("¿Borrar esta suscripción? Lo ya cobrado o facturado se queda; las cuotas pendientes sin factura se borran. Si solo deja de pagar, mejor ponle fecha de baja.")) return;
      if (await call(`/subs/${s.id}`, "DELETE")) { toast("Borrada"); (back || (() => openClient(s.client)))(); }
    }, "btn-danger") : null));
  if (clientId) who.value = clientId;
  else if (!editing && !S.clients.length) { who.value = NEW; who.onchange(); }
}

/* ---------- programas ---------- */

function productForm(p) {
  const editing = !!p;
  p = p || { name: "", plans: [] };
  const name = input({ value: p.name, required: true, placeholder: "p. ej. Mi ERP", maxlength: 80 });
  const box = el("div", { class: "form" });
  const rows = [];
  const addPlan = (x) => {
    const r = { id: x.id, name: input({ value: x.name, placeholder: "Plan (Básico…)", required: true, maxlength: 60 }), price: money(x.price, { required: true, "aria-label": "Precio sin IVA" }),
      period: el("select", { "aria-label": "Cada cuánto" }, ...Object.entries(PERIOD).map(([k, [l]]) => el("option", { value: k, selected: k === (x.period || "year") }, l))) };
    r.row = el("div", { class: "cb-line" }, r.name, r.price, r.period, el("button", { class: "x", type: "button", title: "Quitar plan", onclick: () => { rows.splice(rows.indexOf(r), 1); r.row.remove(); } }, "✕"));
    r.row.classList.add("cb-planrow");
    rows.push(r);
    box.append(r.row);
  };
  (p.plans.length ? p.plans : [{}]).forEach(addPlan);
  sheet(editing ? p.name : "Nuevo programa", "y sus planes (precio sin IVA)",
    form(async () => {
      const res = await call("/products", "POST", { id: p.id, name: name.value,
        plans: rows.map((r) => ({ id: r.id, name: r.name.value, price: num(r.price.value), period: r.period.value })) });
      if (res) { toast("Guardado"); closeSheet(); }
    },
    field("Nombre", name),
    field("Planes", box),
    btn("+ Plan", () => addPlan({})),
    el("p", { class: "cb-note" }, "Cada plan es una columna de la tabla. Cambiar un precio aquí no toca las cuotas ya sacadas."),
    submit(editing ? "Guardar" : "Crear"),
    editing ? btn("Borrar programa", async () => {
      if (!confirm(`¿Borrar ${p.name}?`)) return;
      if (await call(`/products/${p.id}`, "DELETE")) { toast("Borrado"); closeSheet(); }
    }, "btn-danger") : null));
  name.focus();
}

/* ---------- widget de Estado ---------- */

function paintCard() {
  if (!S || !$("cb-owed")) return;
  const s = S.summary;
  $("cb-owed").textContent = eur(s.owed);
  $("cb-card-sub").textContent = s.pending
    ? `${s.pending} pendiente${s.pending === 1 ? "" : "s"} · cobrado este mes ${eur(s.month)}`
    : `Nada pendiente · cobrado este mes ${eur(s.month)}`;
  const badge = $("cb-badge");
  badge.className = `badge ${s.late_n ? "bad" : s.uninvoiced ? "warn" : ""}`;
  badge.textContent = s.late_n ? `${s.late_n} vencido${s.late_n === 1 ? "" : "s"}` : s.uninvoiced ? `${s.uninvoiced} sin factura` : "";
}

export async function loadCard() {
  try {
    S = await api("/api/cobros");
    paintCard();
  } catch { /* el widget se queda como estaba */ }
}

export function init() {
  for (const b of document.querySelectorAll("#cb-tabs .seg-btn")) b.onclick = () => { tab = b.dataset.tab; store.set("tab", tab); renderHub(); };
  for (const b of document.querySelectorAll("#cb-range .seg-btn")) b.onclick = () => { range = b.dataset.range; store.set("range", range); moreMoves = false; renderMoves(); };
  $("cb-prev").onclick = () => step(-1);
  $("cb-next").onclick = () => step(1);
  initSheet();
}

export function show() {
  document.body.classList.add("cb-on");
  const files = document.querySelector('.tabbar a[data-tab="files"]');
  if (!S) $("cb-hub").replaceChildren(empty("Cargando…"));
  else render();
  load().then(() => {
    const a = $("cb-folder");
    a.hidden = !files || !S;
    if (S) a.href = `#files/${encodeURIComponent(S.folder)}`;
  });
}

export function hide() {
  document.body.classList.remove("cb-on");
}

export function leave() {
  document.body.classList.remove("cb-on");
  closeSheet();
}
