import { api, el, fmtAgo, panel, toast } from "./api.js";
import { closeSheet, initSheet, openSheet as sheet } from "./ui.js";

const $ = (id) => document.getElementById(id);
let tab = "users";
let users = [];
let invites = [];
let loaded = false;

const DAY = 86400;

// Última vez: relativo si es reciente; si no, la fecha con año ("15 dic 2025")
function fmtLast(ts) {
  if (!ts) return "nunca";
  return Date.now() / 1000 - ts < 7 * DAY ? fmtAgo(ts) : fmtDate(ts);
}

function fmtDate(ts) {
  return new Date(ts * 1000).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" });
}

function expiryText(u) {
  if (!u.expiry) return ["sin caducidad", ""];
  const left = u.expiry - Date.now() / 1000;
  if (left <= 0) return [`caducó el ${fmtDate(u.expiry)}`, "exp-expired"];
  const d = Math.ceil(left / DAY);
  return [d <= 60 ? `caduca en ${d} día${d === 1 ? "" : "s"}` : `caduca el ${fmtDate(u.expiry)}`, d < 7 ? "exp-soon" : ""];
}

// "hace 1 año y 2 meses" / "hace 8 meses" / "hace 12 días"
function fmtSpan(ts) {
  const days = Math.floor((Date.now() / 1000 - ts) / DAY);
  if (days < 1) return "hoy";
  if (days < 31) return `${days} día${days === 1 ? "" : "s"}`;
  const months = Math.floor(days / 30.44);
  const y = Math.floor(months / 12), m = months % 12;
  const ys = y ? `${y} año${y === 1 ? "" : "s"}` : "";
  const ms = m ? `${m} mes${m === 1 ? "" : "es"}` : "";
  return [ys, ms].filter(Boolean).join(" y ");
}

// "~1 año y 11 meses (oct 2024)": ~ = aproximado (cuenta anterior al registro de actividad de Jellyfin)
function sinceText(u) {
  if (!u.since) return "antes de dic 2025";
  const month = new Date(u.since * 1000).toLocaleDateString("es-ES", { month: "short", year: "numeric" });
  return `${u.since_approx ? "~" : ""}${fmtSpan(u.since)} (${month})`;
}

function avatar(u) {
  const box = el("span", { class: "svc-icon u-avatar" }, u.name[0].toUpperCase());
  if (u.image) {
    // sin loading=lazy: la imagen no está en el DOM hasta que carga y una lazy fuera del DOM nunca se pide
    const img = el("img", { src: `/api/jfa/avatar/${u.id}`, alt: "" });
    img.onerror = () => img.remove();
    img.onload = () => box.replaceChildren(img);
  }
  return box;
}

function inviteUses(i) {
  return i.no_limit ? "usos ilimitados" : `${i.remaining} uso${i.remaining === 1 ? "" : "s"} restante${i.remaining === 1 ? "" : "s"}`;
}

function accountLen(i) {
  if (!i.user_months && !i.user_days) return "cuenta sin caducidad";
  return `cuenta de ${i.user_months ? `${i.user_months} mes${i.user_months === 1 ? "" : "es"}` : `${i.user_days} días`}`;
}

/* ---------- listas ---------- */

function render() {
  const q = $("u-search").value.trim().toLowerCase();
  const list = $("u-list");
  if (tab === "active") {
    const act = users.filter((u) => !u.disabled && (!q || u.name.toLowerCase().includes(q)))
      .sort((a, b) => (a.since ?? 0) - (b.since ?? 0));
    $("u-info").textContent = `${act.length} cuentas activas · de más antigua a más nueva`;
    list.replaceChildren(...(act.length ? act.map((u) => el("li", {}, el("button", { class: "svc", onclick: () => openUser(u.id) },
      avatar(u),
      el("div", { class: "svc-main" },
        el("div", { class: "svc-name" }, el("span", {}, u.name), u.admin ? el("b", { class: "upd-badge" }, "admin") : null),
        el("div", { class: "svc-sub" }, sinceText(u))),
      el("div", { class: "svc-stats" }, fmtLast(u.last_active)))))
      : [el("li", { class: "empty" }, "Sin resultados")]));
    return;
  }
  if (tab === "users") {
    const shown = users.filter((u) => !q || u.name.toLowerCase().includes(q) || (u.email || "").toLowerCase().includes(q));
    const soon = users.filter((u) => u.expiry && u.expiry - Date.now() / 1000 < 7 * DAY && !u.disabled).length;
    $("u-info").textContent = `${users.length} cuentas · ${users.filter((u) => u.disabled).length} desactivadas${soon ? ` · ${soon} caducan esta semana` : ""}`;
    list.replaceChildren(...(shown.length ? shown.map((u) => {
      const [exp, cls] = expiryText(u);
      return el("li", {}, el("button", { class: `svc ${u.disabled ? "u-off" : ""}`, onclick: () => openUser(u.id) },
        avatar(u),
        el("div", { class: "svc-main" },
          el("div", { class: "svc-name" }, el("i", { class: `dot ${u.disabled ? "off" : ""}` }), el("span", {}, u.name),
            u.admin ? el("b", { class: "upd-badge" }, "admin") : null),
          el("div", { class: "svc-sub" }, u.disabled ? el("span", { class: "u-disabled" }, "desactivada") : el("span", { class: cls }, exp))),
        el("div", { class: "svc-stats" }, fmtLast(u.last_active))));
    }) : [el("li", { class: "empty" }, "Sin resultados")]));
  } else {
    const shown = invites.filter((i) => !q || i.label.toLowerCase().includes(q) || i.code.toLowerCase().includes(q));
    $("u-info").textContent = `${invites.length} invitaciones activas`;
    list.replaceChildren(...(shown.length ? shown.map((i) => el("li", {}, el("button", { class: "svc", onclick: () => openInvite(i.code) },
      el("span", { class: "svc-icon" }, "✉"),
      el("div", { class: "svc-main" },
        el("div", { class: "svc-name" }, el("span", {}, i.label || i.code)),
        el("div", { class: "svc-sub" }, `${inviteUses(i)} · ${accountLen(i)}`)),
      el("div", { class: "svc-stats" }, i.valid_till ? `hasta ${fmtDate(i.valid_till)}` : ""))))
      : [el("li", { class: "empty" }, "No hay invitaciones activas. Crea una con + Nueva")]));
  }
}

async function load() {
  try {
    [users, invites] = await Promise.all([api("/api/jfa/users"), api("/api/jfa/invites")]);
    loaded = true;
    render();
  } catch (e) {
    if (e.message !== "no autenticado") {
      $("u-list").replaceChildren(el("li", { class: "empty" }, `No se pudo hablar con jfa-go: ${e.message}`));
    }
  }
}

function setTab(t) {
  tab = t;
  for (const b of document.querySelectorAll("#view-users .seg-btn")) b.classList.toggle("active", b.dataset.utab === t);
  render();
}

/* ---------- ficha ---------- */

async function act(path, opts, okMsg) {
  try {
    await api(path, opts);
    toast(okMsg);
    await load();
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  }
}

function openUser(id) {
  const u = users.find((x) => x.id === id);
  if (!u) return;
  const [exp, cls] = expiryText(u);
  const extend = (body, label) => act(`/api/jfa/users/${id}/extend`, { method: "POST", body }, `${u.name}: ${label}`).then((ok) => ok && openUser(id));
  const dateInput = el("input", { type: "date", "aria-label": "Fecha de caducidad" });
  sheet(u.name, u.disabled ? "cuenta desactivada" : exp,
    el("dl", { class: "kv" },
      el("dt", {}, "Estado"), el("dd", { class: u.disabled ? "u-disabled" : "" }, u.disabled ? "Desactivada" : "Activa"),
      el("dt", {}, "Caducidad"), el("dd", { class: cls }, u.expiry ? `${fmtDate(u.expiry)} (${exp})` : "Sin caducidad"),
      el("dt", {}, "Usuario desde"), el("dd", {}, sinceText(u)),
      el("dt", {}, "Última vez"), el("dd", {}, fmtLast(u.last_active)),
      u.email ? [el("dt", {}, "Email"), el("dd", {}, u.email)] : null,
      u.telegram ? [el("dt", {}, "Telegram"), el("dd", {}, u.telegram)] : null),
    el("h3", { class: "section-title" }, "Alargar caducidad"),
    el("div", { class: "btn-row" },
      el("button", { class: "btn", onclick: () => extend({ months: 1 }, "+1 mes") }, "+1 mes"),
      el("button", { class: "btn", onclick: () => extend({ months: 3 }, "+3 meses") }, "+3 meses"),
      el("button", { class: "btn", onclick: () => extend({ months: 12 }, "+1 año") }, "+1 año")),
    el("div", { class: "btn-row" }, dateInput,
      el("button", { class: "btn", onclick: () => {
        if (!dateInput.value) return toast("Elige una fecha", true);
        const ts = Math.floor(new Date(`${dateInput.value}T23:59:00`).getTime() / 1000);
        extend({ timestamp: ts }, `caduca el ${fmtDate(ts)}`);
      } }, "Poner fecha"),
      u.expiry ? el("button", { class: "btn", onclick: () => act(`/api/jfa/users/${id}/no-expiry`, { method: "POST" }, `${u.name}: sin caducidad`).then((ok) => ok && openUser(id)) }, "Quitar caducidad") : null),
    el("h3", { class: "section-title" }, "Cuenta"),
    el("div", { class: "btn-row" },
      el("button", { class: "btn", onclick: () => act(`/api/jfa/users/${id}/${u.disabled ? "enable" : "disable"}`, { method: "POST" },
        `${u.name} ${u.disabled ? "activada" : "desactivada"}`).then((ok) => ok && openUser(id)) }, u.disabled ? "Activar" : "Desactivar"),
      el("button", { class: "btn btn-danger", onclick: async () => {
        if (!confirm(`¿Borrar la cuenta de ${u.name}? No se puede deshacer.`)) return;
        if (await act(`/api/jfa/users/${id}/delete`, { method: "POST" }, `${u.name} borrado`)) closeSheet();
      } }, "Borrar")));
  dateInput.style.flex = "1 1 150px";
  dateInput.className = "form-date";
}

async function share(link, label) {
  if (navigator.share) {
    try { await navigator.share({ title: "Invitación a PichaFlix", text: label ? `Invitación a PichaFlix (${label})` : "Invitación a PichaFlix", url: link }); return; } catch { /* cancelado */ }
  }
  try { await navigator.clipboard.writeText(link); toast("Enlace copiado"); } catch { toast("No se pudo copiar; mantén pulsado el enlace", true); }
}

function openInvite(code) {
  const i = invites.find((x) => x.code === code);
  if (!i) return;
  sheet(i.label || "Invitación", `${inviteUses(i)} · ${accountLen(i)}`,
    el("div", { class: "linkbox" }, i.link),
    el("div", { class: "btn-row" },
      el("button", { class: "btn btn-primary", onclick: () => share(i.link, i.label) }, "Compartir"),
      el("button", { class: "btn", onclick: async () => { try { await navigator.clipboard.writeText(i.link); toast("Enlace copiado"); } catch { toast("No se pudo copiar", true); } } }, "Copiar")),
    el("dl", { class: "kv" },
      el("dt", {}, "Enlace válido hasta"), el("dd", {}, i.valid_till ? fmtDate(i.valid_till) : "—"),
      el("dt", {}, "Creada"), el("dd", {}, i.created ? fmtAgo(i.created) : "—"),
      i.used_by.length ? [el("dt", {}, "Usada por"), el("dd", {}, i.used_by.join(", "))] : null),
    el("div", { class: "btn-row" },
      el("button", { class: "btn btn-danger", onclick: async () => {
        if (!confirm("¿Borrar esta invitación? El enlace dejará de funcionar.")) return;
        if (await act(`/api/jfa/invites/${encodeURIComponent(code)}`, { method: "DELETE" }, "Invitación borrada")) closeSheet();
      } }, "Borrar invitación")));
}

/* ---------- formularios ---------- */

function chips(options, initial) {
  let value = initial;
  const box = el("div", { class: "chips" });
  const draw = () => box.replaceChildren(...options.map(([v, label]) =>
    el("button", { type: "button", class: v === value ? "on" : "", onclick: () => { value = v; draw(); } }, label)));
  draw();
  return { box, get: () => value };
}

function newInvite() {
  const label = el("input", { placeholder: "Para quién es (opcional)", maxlength: 60 });
  const uses = chips([[1, "1 persona"], [5, "5 personas"], [0, "Sin límite"]], 1);
  const valid = chips([[1, "1 día"], [7, "7 días"], [30, "30 días"]], 7);
  const months = chips([[0, "Sin caducidad"], [1, "1 mes"], [3, "3 meses"], [6, "6 meses"], [12, "1 año"]], 1);
  const go = el("button", { class: "btn btn-primary", type: "submit" }, "Crear invitación");
  const form = el("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    go.disabled = true;
    try {
      const inv = await api("/api/jfa/invites", { method: "POST",
        body: { label: label.value, uses: uses.get(), valid_days: valid.get(), user_months: months.get() } });
      await load();
      setTab("invites");
      openInvite(inv.code);
      toast("Invitación creada");
    } catch (ex) {
      toast(ex.message, true);
      go.disabled = false;
    }
  } },
  el("label", {}, "Etiqueta", label),
  el("label", {}, "¿Cuántas personas pueden usarla?", uses.box),
  el("label", {}, "El enlace caduca en", valid.box),
  el("label", {}, "La cuenta creada dura", months.box),
  go);
  sheet("Nueva invitación", panel.jellyfin.public_url ? `se registran en ${new URL(panel.jellyfin.public_url).host}` : "", form,
    el("button", { class: "btn", onclick: newUser }, "…o crear una cuenta directamente"));
  label.focus();
}

function newUser() {
  const name = el("input", { required: true, autocomplete: "off", autocapitalize: "none", placeholder: "nombre" });
  const pass = el("input", { required: true, type: "text", minlength: 6, autocomplete: "off", placeholder: "mínimo 6 caracteres" });
  const email = el("input", { type: "email", placeholder: "opcional" });
  const months = chips([[0, "Sin caducidad"], [1, "1 mes"], [3, "3 meses"], [12, "1 año"]], 1);
  const go = el("button", { class: "btn btn-primary", type: "submit" }, "Crear cuenta");
  sheet("Nueva cuenta", "sin invitación, con el perfil por defecto", el("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    go.disabled = true;
    try {
      await api("/api/jfa/users", { method: "POST", body: { username: name.value, password: pass.value, email: email.value, months: months.get() } });
      toast(`Cuenta ${name.value} creada`);
      await load();
      setTab("users");
      const u = users.find((x) => x.name.toLowerCase() === name.value.trim().toLowerCase());
      if (u) openUser(u.id); else closeSheet();
    } catch (ex) {
      toast(ex.message, true);
      go.disabled = false;
    }
  } },
  el("label", {}, "Usuario", name), el("label", {}, "Contraseña", pass), el("label", {}, "Email", email),
  el("label", {}, "Caducidad", months.box), go));
  name.focus();
}

export function init() {
  $("u-search").addEventListener("input", render);
  for (const b of document.querySelectorAll("#view-users .seg-btn")) b.onclick = () => setTab(b.dataset.utab);
  $("u-new").onclick = newInvite;
  initSheet();
}

export function show() {
  if (!loaded) $("u-list").replaceChildren(el("li", { class: "empty" }, "Cargando…"));
  load();
}

export function leave() {
  closeSheet();
}
