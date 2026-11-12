// Clientes: dónde se sirven las webs, la VM, las copias, el DNS, las tareas programadas y sus acciones.
import { api, el, fmtAgo, fmtBytes, fmtUptime, toast } from "/js/api.js";
import { closeRunner, closeSheet, initSheet, openRunner, openSheet, runnerOut, setRunnerStatus, watchJob } from "/js/ui.js";

const $ = (id) => document.getElementById(id);
const DONE = { ok: ["✓ terminado", true], failed: ["✗ ha fallado (mira arriba por qué)", false] };
const S = { st: null, ver: null, bk: null, dns: null, cron: null, ev: null };
let timer = null;        // refresco mientras la pestaña está abierta
let jobWas = false;      // había una acción en marcha la última vez que se miró
let evFilter = "main";
let evMore = false;

const when = (ts) => new Date(ts * 1000).toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const badge = (text, kind = "") => el("span", { class: `badge ${kind}` }, text);
const empty = (text) => el("p", { class: "cl-empty" }, text);
const note = (text) => el("p", { class: "cl-note" }, text);
const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);
const put = (box, ...kids) => box.replaceChildren(...kids.flat().filter((k) => k != null));
const field = (label, input, help) => el("label", {}, label, input, help ? el("span", { class: "help" }, help) : null);

/* ---------------------------------------------------------------- carga */

async function get(key, url, render) {
  try {
    S[key] = await api(url);
  } catch (e) {
    if (e.message === "no autenticado") return;
    S[key] = { failed: e.message };
  }
  render();
}

function loadStatus() {
  return get("st", "/api/clientes", () => {
    renderHero();
    renderProjects();
    renderVm();
    const st = S.st;
    if (!st || st.failed) return;
    const b = $("cl-job");
    b.hidden = !st.job.running;
    b.textContent = `⏳ ${st.job.name}…`;
    if (jobWas && !st.job.running) {  // acaba de terminar algo: se relee todo
      toast(st.job.failed ? `Ha fallado: ${st.job.name}` : `Terminado: ${st.job.name}`, st.job.failed);
      loadRest(true);
    }
    jobWas = st.job.running;
    schedule();
  });
}

function loadRest(fresh = false) {
  get("ver", `/api/clientes/versiones${fresh ? "?fresh=1" : ""}`, renderProjects);
  get("bk", "/api/clientes/copias", renderBackups);
  get("dns", "/api/clientes/dns", renderDns);
  get("cron", "/api/clientes/crons", renderCrons);
  get("ev", "/api/clientes/sucesos", renderEvents);
}

function schedule() {
  clearTimeout(timer);
  if ($("view-clientes").hidden) return;
  timer = setTimeout(() => { if (!document.hidden) loadStatus(); else schedule(); }, S.st?.job?.running ? 5000 : 30000);
}

async function run(body, title) {
  try {
    const r = await api("/api/clientes/run", { method: "POST", body });
    closeSheet();
    jobWas = true;
    watchJob("/api/clientes/job", title || r.name, DONE, () => { jobWas = false; loadStatus(); loadRest(true); });
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  }
}

/* ---------------------------------------------------------------- arriba */

function renderHero() {
  const box = $("cl-hero"), st = S.st;
  if (!st) return;
  if (st.failed) { box.className = "cl-card cl-hero bad"; return box.replaceChildren(empty(`No se pudo leer el estado: ${st.failed}`)); }
  const home = st.mode === "casa", unknown = st.mode === "desconocido";
  const up = st.projects.filter((p) => p.ok).length;
  const title = unknown ? "No se sabe dónde están servidas" : home ? "Servidas desde casa (relevo)" : "Servidas desde la VM de Oracle";
  const bits = [`${up} de ${st.projects.length} webs responden`];
  if (home && st.since) bits.push(`en casa desde el ${st.since.slice(0, 16)}`);
  if (st.backup_at) bits.push(`última copia ${fmtAgo(st.backup_at)}`);
  if (st.vigil.maintenance) bits.push("mantenimiento en curso (la vigilancia espera)");
  else if (st.vigil.fails) bits.push(`la VM lleva ${st.vigil.fails} de 3 fallos seguidos`);
  const node = (text, cls) => el("span", { class: `cl-node ${cls}` }, text);
  const arrow = () => el("span", { class: "cl-arrow" }, "→");
  const flow = el("div", { class: "cl-flow" }, node("Visitante", ""), arrow(), node("Cloudflare", ""), arrow(),
    node(`☁ VM${home ? " (parada o en reserva)" : ""}`, home ? (st.vm.ok ? "off" : "down") : st.vm.ok ? "on" : "down"),
    el("span", { class: "cl-arrow" }, "o"),
    node(`🏠 Casa${home ? "" : " (en reserva)"}`, home ? "on" : "off"));
  const btn = home
    ? el("button", { class: "btn btn-primary", type: "button", onclick: toVm }, "Volver a la VM")
    : el("button", { class: "btn", type: "button", onclick: toHome }, "Pasar a casa");
  box.className = `cl-card cl-hero ${st.level === "ok" ? "" : st.level}`;
  put(box,
    el("div", { class: "cl-hero-top" },
      el("span", { class: "cl-hero-ico" }, unknown ? "?" : home ? "🏠" : "☁"),
      el("div", { class: "cl-hero-text" }, el("b", {}, title), el("span", {}, bits.join(" · "))),
      unknown ? null : btn),
    flow,
    st.problems.length ? el("ul", { class: `cl-problems ${st.level === "bad" ? "cl-bad" : "cl-warn"}` }, st.problems.map((p) => el("li", {}, p))) : null);
}

function toHome() {
  confirmSheet("Pasar los clientes a casa", "casa", [
    "Las webs pasarán a servirse desde este servidor con los datos de la ÚLTIMA COPIA" + (S.st?.backup_at ? ` (${when(S.st.backup_at)})` : "") + ".",
    "Lo que los clientes hayan guardado en la VM después de esa copia no estará en casa. Si la VM funciona, haz antes «Copiar ahora».",
    "Esto es lo mismo que hace la vigilancia sola cuando la VM cae. Se tarda en torno a un minuto.",
  ], "Pasar a casa", () => run({ action: "a-casa", confirm: "casa" }));
}

function toVm() {
  confirmSheet("Volver a la VM", "vm", [
    "Proyecto a proyecto: se para en casa, se copian sus datos a la VM, se arranca allí, se comprueba y se cambia el DNS.",
    "Si alguno no arranca bien en la VM, sigue en casa y el proceso se detiene sin perder datos.",
  ], "Volver a la VM", () => run({ action: "a-la-vm", confirm: "vm" }));
}

/** Ficha que pide escribir una palabra para confirmar algo delicado. */
function confirmSheet(title, word, texts, action, onok, extra) {
  initSheet();
  const input = el("input", { type: "text", autocomplete: "off", autocapitalize: "none", spellcheck: "false", placeholder: word });
  const ok = el("button", { class: "btn btn-danger", type: "button", disabled: true }, action);
  input.oninput = () => { ok.disabled = input.value.trim() !== word; };
  ok.onclick = async () => { ok.disabled = true; if (!(await onok())) ok.disabled = false; };
  openSheet(title, "", el("div", { class: "cl-sheet" },
    ...texts.map((t) => el("p", {}, t)), extra,
    el("div", { class: "cl-danger-box form" }, field(`Para confirmar, escribe «${word}»`, input),
      el("div", { class: "sheet-actions" }, el("button", { class: "btn", type: "button", onclick: closeSheet }, "Cancelar"), ok))));
}

/* ---------------------------------------------------------------- proyectos */

function versionOf(p) {
  const remote = S.ver && !S.ver.failed ? S.ver[p.name] : undefined;
  if (p.failed) return ["bad", `Falló ${p.failed}`, "El último commit no se pudo publicar; sigue la versión anterior."];
  if (!p.deployed) return ["warn", "Sin desplegar", ""];
  if (remote === undefined) return ["", "…", ""];
  if (remote === null) return ["", "GitHub no responde", ""];
  if (remote !== p.deployed) return ["warn", `Pendiente ${remote}`, "Hay cambios en main; se publican esta noche (o con «Desplegar ahora»)."];
  return ["ok", "Al día", "Lo publicado es lo último de main."];
}

function renderProjects() {
  const box = $("cl-projects"), st = S.st;
  if (!st || st.failed) return box.replaceChildren(empty(st ? "Sin datos" : "Cargando…"));
  if (!st.projects.length) return box.replaceChildren(empty("No hay proyectos. Añade el primero con «+ Proyecto»."));
  box.replaceChildren(...st.projects.map((p) => {
    const [vk, vt, vtitle] = versionOf(p);
    return el("button", { class: "cl-row cl-proj", type: "button", onclick: () => projectSheet(p.name) },
      el("span", { class: `dot ${p.ok ? "" : "off"}` }),
      el("div", { class: "cl-main" }, el("span", { class: "cl-name" }, p.name), el("span", { class: "cl-sub" }, p.domains.join(" · "))),
      el("div", { class: "cl-ver" },
        el("span", { class: "cl-sub mono" }, p.deployed ? `${p.deployed} · ${p.deployed_at ? fmtAgo(p.deployed_at) : ""}` : "–"),
        el("span", { class: "cl-sub", title: p.commit_msg }, p.commit_msg || "")),
      el("div", { class: "cl-right" },
        badge(vt, vk), Object.assign(badge(p.public_ok ? `Responde · ${p.time_public ?? "?"} s` : `No responde (${p.http_public || "sin conexión"})`, p.public_ok ? "ok" : "bad"), { title: vtitle })));
  }));
}

function projectSheet(name) {
  const p = S.st?.projects.find((x) => x.name === name);
  if (!p) return;
  initSheet();
  const [vk, vt, vtitle] = versionOf(p);
  const here = S.st.mode === "casa" ? p.home : p.vm;
  const btn = (text, fn, cls = "") => el("button", { class: `btn ${cls}`, type: "button", onclick: fn }, text);
  openSheet(p.name, p.domains.join(" · "), el("div", { class: "cl-sheet" },
    el("dl", { class: "cl-kv" },
      el("dt", {}, "Desde fuera"), el("dd", { class: p.public_ok ? "cl-ok" : "cl-bad" }, p.public_ok ? `responde (HTTP ${p.http_public}, ${p.time_public} s)` : `no responde (${p.http_public || "sin conexión"})`),
      el("dt", {}, "Dentro de la VM"), el("dd", {}, p.http_vm ? `HTTP ${p.http_vm}` : "–"),
      el("dt", {}, "Contenedor"), el("dd", {}, here ? here.status : "no existe"),
      el("dt", {}, "Versión publicada"), el("dd", { class: "mono" }, p.deployed || "–"),
      el("dt", {}, "Último cambio"), el("dd", {}, p.commit_msg || "–"),
      el("dt", {}, "Frente a GitHub"), el("dd", { class: vk ? `cl-${vk}` : "" }, vtitle || vt),
      el("dt", {}, "Repositorio"), el("dd", {}, el("a", { class: "link", href: `https://github.com/${p.repo}`, target: "_blank", rel: "noopener" }, p.repo)),
      el("dt", {}, "Tipo"), el("dd", {}, p.type === "docker" ? "Aplicación (Docker)" : "Web estática"),
      el("dt", {}, "Puerto interno"), el("dd", {}, String(p.port)),
      el("dt", {}, "Datos"), el("dd", {}, p.data ? "sí, se copian cada noche" : "no guarda datos"),
      el("dt", {}, "Se comprueba"), el("dd", { class: "mono" }, `${p.domains[0]}${p.path}`)),
    el("div", { class: "btn-row" },
      el("a", { class: "btn", href: `https://${p.domains[0]}${p.path}`, target: "_blank", rel: "noopener" }, "Abrir la web"),
      btn("Ver logs", () => { closeSheet(); showLogs(p.name); }),
      btn("Reiniciar", () => confirm(`¿Reiniciar ${p.name}? La web se corta unos segundos.`) && run({ action: "reiniciar", name: p.name })),
      btn("Desplegar ahora", () => confirm(`¿Publicar ahora lo que haya en main de ${p.repo}?\n\nNormalmente se publica solo cada noche. Si la versión nueva falla, se vuelve sola a la anterior.`) && run({ action: "desplegar", name: p.name })),
      btn("Editar", () => editForm(p)),
      p.data ? btn("Restaurar una copia", () => restoreSheet(p)) : null,
      btn("Quitar proyecto", () => removeSheet(p), "btn-danger"))));
}

function removeSheet(p) {
  confirmSheet(`Quitar ${p.name}`, p.name, [
    `Se para y se quita de la VM y de casa, se borran sus registros DNS (${p.domains.join(", ")}) y deja de copiarse, vigilarse y publicarse.`,
    "Sus datos NO se borran: se apartan en una carpeta «.quitado» en la VM y en casa.",
  ], "Quitar", () => run({ action: "quitar", name: p.name, confirm: p.name }));
}

function restoreSheet(p) {
  initSheet();
  const snaps = S.bk?.snapshots || [];
  if (!snaps.length) return toast("Todavía no se ha cargado el historial de copias", true);
  let chosen = null;
  const list = el("div", { class: "cl-pick" }, snaps.map((s) => el("label", {},
    el("input", { type: "radio", name: "cl-snap", onchange: () => { chosen = s; step(); } }),
    el("span", { style: "flex:1" }, when(s.at)), el("span", { class: "muted small" }, `${s.tag === "casa" ? "datos de casa" : "datos de la VM"} · ${fmtBytes(s.size)}`))));
  const next = el("button", { class: "btn btn-primary", type: "button", disabled: true }, "Continuar");
  const step = () => { next.disabled = !chosen; };
  next.onclick = () => confirmSheet(`Restaurar ${p.name}`, p.name, [
    `Los datos de ${p.name} volverán a como estaban el ${when(chosen.at)}. Todo lo guardado después dejará de verse.`,
    "Antes se guarda una copia de cómo están ahora, así que se puede deshacer restaurando esa copia.",
    "La web se corta alrededor de un minuto.",
  ], "Restaurar", () => run({ action: "restaurar", name: p.name, snapshot: chosen.id, confirm: p.name }));
  openSheet(`Restaurar ${p.name}`, "Elige a qué copia volver", el("div", { class: "cl-sheet" },
    note("Solo se cambian los datos de este proyecto; los demás no se tocan."), list,
    el("div", { class: "sheet-actions" }, el("button", { class: "btn", type: "button", onclick: closeSheet }, "Cancelar"), next)));
}

function projectForm({ title, sub, p, submit, action }) {
  initSheet();
  const isNew = !p;
  const used = (S.st?.projects || []).map((x) => x.port);
  const name = el("input", { type: "text", autocapitalize: "none", spellcheck: "false", placeholder: "mitienda" });
  const repo = el("input", { type: "text", autocapitalize: "none", spellcheck: "false", placeholder: "usuario/repositorio" });
  const type = el("select", {}, el("option", { value: "web" }, "Web estática (HTML, se sirve con nginx)"), el("option", { value: "docker" }, "Aplicación con Dockerfile"));
  const port = el("input", { type: "number", min: "1024", max: "65535", value: p ? p.port : (used.length ? Math.min(...used) - 1 : 8085) });
  const data = el("input", { type: "checkbox" });
  const path = el("input", { type: "text", autocapitalize: "none", spellcheck: "false", value: p ? p.path : "/" });
  const domains = el("textarea", { rows: 3, autocapitalize: "none", spellcheck: "false", placeholder: "mitienda.com\nwww.mitienda.com" }, p ? p.domains.join("\n") : "");
  const err = el("p", { class: "form-error", hidden: true });
  const ok = el("button", { class: "btn btn-primary", type: "submit" }, action);
  const form = el("form", { class: "form" },
    isNew ? field("Nombre", name, "Corto, en minúsculas. Será el nombre del contenedor y de sus carpetas.") : null,
    isNew ? field("Repositorio de GitHub", repo, "Se publica lo que haya en la rama main.") : null,
    isNew ? field("Tipo", type) : null,
    field("Dominios", domains, "Uno por línea. El primero es el principal. El dominio tiene que estar ya en tu Cloudflare."),
    field("Puerto interno", port, "Un puerto libre, distinto para cada proyecto. No se ve desde fuera."),
    field("Ruta de comprobación", path, "La dirección que debe responder para darlo por vivo (p. ej. / o /login)."),
    isNew ? el("label", { class: "cl-check" }, data, "Guarda datos (se copian cada noche y se llevan en los relevos)") : null,
    err,
    el("div", { class: "sheet-actions" }, el("button", { class: "btn", type: "button", onclick: closeSheet }, "Cancelar"), ok));
  form.onsubmit = async (e) => {
    e.preventDefault();
    err.hidden = true;
    const body = { port: Number(port.value), path: path.value.trim(), domains: domains.value.split(/[\s,]+/).filter(Boolean).map((d) => d.toLowerCase()) };
    if (isNew) Object.assign(body, { name: name.value.trim(), repo: repo.value.trim().replace(/^https:\/\/github\.com\//, "").replace(/\.git$/, ""), type: type.value, data: data.checked });
    ok.disabled = true;
    try {
      await submit(body);
    } catch (e2) {
      err.textContent = e2.message;
      err.hidden = false;
    }
    ok.disabled = false;
  };
  openSheet(title, sub, form);
}

function newForm() {
  projectForm({
    title: "Proyecto nuevo", sub: "Se clona, se publica en la VM, se crea su DNS y entra en copias y vigilancia", action: "Dar de alta",
    submit: async (b) => {
      const r = await api("/api/clientes/run", { method: "POST", body: { action: "nuevo", ...b } });
      closeSheet();
      jobWas = true;
      watchJob("/api/clientes/job", r.name, DONE, () => { jobWas = false; loadStatus(); loadRest(true); });
    },
  });
}

function editForm(p) {
  projectForm({
    title: `Editar ${p.name}`, sub: "Dominios, puerto y ruta de comprobación", p, action: "Guardar",
    submit: async (b) => {
      const r = await api("/api/clientes/run", { method: "POST", body: { action: "editar", name: p.name, ...b } });
      closeSheet();
      jobWas = true;
      watchJob("/api/clientes/job", r.name, DONE, () => { jobWas = false; loadStatus(); loadRest(true); });
    },
  });
}

/* ---------------------------------------------------------------- logs */

function showLogs(name) {
  let t = null, stop = false;
  openRunner(`Logs de ${name}`, "cargando…", () => { stop = true; clearTimeout(t); });
  const poll = async () => {
    if (stop) return;
    if (!document.hidden) {
      try {
        const r = await api(`/api/clientes/logs?name=${encodeURIComponent(name)}&lines=300`);
        if (stop) return;
        const out = $("run-out"), stuck = out.scrollTop + out.clientHeight >= out.scrollHeight - 30;
        const top = out.scrollTop;
        runnerOut(r.lines.join("\n") || "(sin líneas)");
        if (!stuck) out.scrollTop = top;  // si has subido a leer, no te baja
        setRunnerStatus("en vivo · últimas 300 líneas · se actualiza cada 4 s");
      } catch (e) {
        setRunnerStatus(`sin conexión, reintento… (${e.message})`);
      }
    }
    t = setTimeout(poll, 4000);
  };
  poll();
}

/* ---------------------------------------------------------------- VM */

function meter(label, used, total, text) {
  const p = pct(used, total);
  return el("div", { class: "cl-meter" },
    el("div", { class: "cl-meter-head" }, el("span", {}, label), el("span", {}, text)),
    el("div", { class: `bar ${p >= 90 ? "bad" : p >= 75 ? "warn" : ""}` }, el("i", { style: `width:${Math.min(100, p)}%` })));
}

function renderVm() {
  const box = $("cl-vm"), b = $("cl-vm-badge"), st = S.st;
  if (!st || st.failed) return box.replaceChildren(empty(st ? "Sin datos" : "Cargando…"));
  const vm = st.vm;
  b.textContent = vm.ok ? "Encendida" : "No responde";
  b.className = `badge ${vm.ok ? "ok" : "bad"}`;
  if (!vm.ok) {
    return box.replaceChildren(el("p", { class: "cl-bad", style: "margin:0" }, `No se puede entrar en la VM (${vm.ip}).`),
      note(st.mode === "casa" ? "Los clientes están en casa. Cuando la VM vuelva, usa «Volver a la VM»." : "Si sigue así 15 minutos, la vigilancia pasa los clientes a casa sola."));
  }
  const cs = Object.entries(vm.containers);
  box.replaceChildren(
    el("dl", { class: "cl-kv" },
      el("dt", {}, "Dirección"), el("dd", { class: "mono" }, vm.ip),
      el("dt", {}, "Encendida desde hace"), el("dd", {}, fmtUptime(vm.uptime))),
    meter("Procesador", vm.load[0], vm.cpus, `carga ${vm.load[0].toFixed(2)} de ${vm.cpus}`),
    meter("Memoria", vm.mem_used, vm.mem_total, `${fmtBytes(vm.mem_used)} de ${fmtBytes(vm.mem_total)}`),
    meter("Disco", vm.disk_used, vm.disk_total, `${fmtBytes(vm.disk_used)} de ${fmtBytes(vm.disk_total)}`),
    el("div", { class: "cl-chips" }, cs.map(([n, c]) => Object.assign(badge(`${c.state === "running" ? "●" : "○"} ${n}`, c.state === "running" ? "ok" : "bad"), { title: c.status }))),
    el("div", { class: "cl-btns" },
      el("button", { class: "btn btn-sm", type: "button", onclick: () => showLogs("proxy") }, "Logs del proxy"),
      el("button", { class: "btn btn-sm", type: "button", title: "docker compose up -d: arranca lo que esté parado",
        onclick: () => run({ action: "levantar" }) }, "Levantar lo parado")));
}

/* ---------------------------------------------------------------- copias */

function renderBackups() {
  const box = $("cl-backups"), b = $("cl-bk-badge"), k = S.bk;
  if (!k) return;
  if (k.failed) return box.replaceChildren(empty(`No se pudo leer: ${k.failed}`));
  const age = k.last ? Date.now() / 1000 - k.last : Infinity;
  b.textContent = !k.last ? "Sin copias" : age > 26 * 3600 ? "Atrasada" : "Al día";
  b.className = `badge ${!k.last ? "bad" : age > 26 * 3600 ? "warn" : "ok"}`;
  const top = k.snapshots.slice(0, 5), rest = k.snapshots.slice(5);
  const row = (s) => el("div", { class: "cl-snap" }, el("span", {}, when(s.at)), el("span", { class: "muted" }, `${s.tag === "casa" ? "casa" : "VM"} · ${fmtBytes(s.size)} · ${s.id}`));
  put(box,
    el("dl", { class: "cl-kv" },
      el("dt", {}, "Última copia"), el("dd", {}, k.last ? `${when(k.last)} (${fmtAgo(k.last)})` : "ninguna"),
      el("dt", {}, "Qué se copia"), el("dd", {}, k.data.length ? k.data.map((d) => `${d.name} (${fmtBytes(d.size)})`).join(", ") : "–"),
      el("dt", {}, "Copias en el historial"), el("dd", {}, `${k.snapshots.length} · ocupan ${fmtBytes(k.repo_size)}`),
      el("dt", {}, "Sitio libre en el disco"), el("dd", {}, k.disk ? `${fmtBytes(k.disk.free)} de ${fmtBytes(k.disk.total)}` : "–"),
      el("dt", {}, "Integridad comprobada"), el("dd", {}, k.checked_at ? fmtAgo(k.checked_at) : "nunca desde el panel")),
    el("div", { class: "cl-snaps" }, ...top.map(row),
      rest.length ? el("details", {}, el("summary", {}, `Ver las ${rest.length} anteriores`), ...rest.map(row)) : null),
    note("Se guardan 7 diarias, 8 semanales y 12 mensuales. Para volver atrás un proyecto: tócalo y «Restaurar una copia»."),
    el("div", { class: "cl-btns" },
      el("button", { class: "btn btn-sm btn-primary", type: "button",
        onclick: () => confirm("¿Hacer una copia ahora?\n\nLos proyectos con datos se paran unos segundos para que la copia sea coherente.") && run({ action: "copiar" }) }, "Copiar ahora"),
      el("button", { class: "btn btn-sm", type: "button", title: "restic check: comprueba que el historial no está dañado",
        onclick: () => run({ action: "comprobar-copias" }) }, "Comprobar integridad")));
}

/* ---------------------------------------------------------------- DNS */

function renderDns() {
  const box = $("cl-dns"), b = $("cl-dns-badge"), d = S.dns;
  if (!d) return;
  if (d.failed) return box.replaceChildren(empty(`No se pudo leer: ${d.failed}`));
  const wrong = d.records.filter((r) => !r.ok);
  b.textContent = d.errors.length ? "Cloudflare no responde" : wrong.length ? `${wrong.length} mal` : "Correcto";
  b.className = `badge ${d.errors.length || wrong.length ? "bad" : "ok"}`;
  const where = (ip) => (ip === d.vm_ip ? "VM" : ip === d.home_ip ? "casa" : "otra máquina");
  const rows = d.records.map((r) => el("div", { class: "cl-row cl-wrap" },
    el("span", { class: `cl-cloud ${r.proxied ? "orange" : ""}`, title: r.proxied ? "Nube naranja: pasa por Cloudflare" : "Nube gris: va directo" }),
    el("div", { class: "cl-main" }, el("span", { class: "cl-name" }, r.name),
      el("span", { class: "cl-sub" }, r.content ? `${r.type} → ${r.content} (${where(r.content)})${r.kind === "casa" ? " · siempre a casa" : ""}` : "no existe"),
      r.ok ? null : el("span", { class: "cl-sub cl-bad" }, r.why)),
    el("div", { class: "cl-right" }, badge(r.ok ? "✓" : "✗", r.ok ? "ok" : "bad"))));
  const fixable = wrong.some((r) => r.kind === "cliente");
  box.replaceChildren(...rows, el("div", { class: "cl-foot" },
    el("span", {}, `Dominios activos en Cloudflare: ${d.zones.map((z) => `${z.name}${z.status === "active" ? "" : ` (${z.status})`}`).join(", ") || "–"}`),
    el("span", {}, `IP de casa: ${d.home_ip || "?"} · Marca de relevo: ${d.flag ? "puesta" : "no"}`),
    fixable ? el("button", { class: "btn btn-sm btn-primary", type: "button",
      onclick: () => confirm(`¿Poner los dominios de clientes apuntando a ${d.mode === "casa" ? "casa" : "la VM"}?`) && run({ action: "dns-corregir" }) }, "Corregir") : null));
}

/* ---------------------------------------------------------------- tareas programadas */

async function cronOp(body, question) {
  if (question && !confirm(question)) return;
  try {
    await api("/api/clientes/cron", { method: "POST", body });
    toast("Hecho");
  } catch (e) {
    toast(e.message, true);
  }
  get("cron", "/api/clientes/crons", renderCrons);
  get("ev", "/api/clientes/sucesos", renderEvents);
}

function renderCrons() {
  const box = $("cl-crons"), b = $("cl-cron-badge"), c = S.cron;
  if (!c) return;
  if (c.failed) return box.replaceChildren(empty(`No se pudo leer: ${c.failed}`));
  const paused = c.crons.filter((x) => x.paused || !x.present).length;
  b.textContent = paused ? `${paused} en pausa` : "Todas activas";
  b.className = `badge ${paused ? "warn" : "ok"}`;
  const rows = c.crons.map((x) => {
    const late = x.id !== "noche" && !x.paused && x.last && c.now - x.last > 20 * 60;
    const last = x.last ? `última vez ${fmtAgo(x.last)}` : "aún sin registrar";
    const extra = x.id === "noche" && x.deploy?.at ? ` · despliegue ${x.deploy.errors ? `con ${x.deploy.errors} fallo(s)` : "bien"}` : "";
    return el("div", { class: "cl-row cl-wrap" },
      el("span", { class: `dot ${x.paused || !x.present || late ? "off" : ""}` }),
      el("div", { class: "cl-main" }, el("span", { class: "cl-name" }, x.title),
        el("span", { class: "cl-sub" }, x.desc),
        el("span", { class: `cl-sub ${x.paused || late ? "cl-warn" : ""}` },
          !x.present ? "No está en el crontab" : x.paused ? `EN PAUSA. ${x.risk}` : `${x.schedule} · ${last}${extra}${late ? " (debería haberse ejecutado ya)" : ""}`)),
      el("div", { class: "cl-right" },
        x.id === "noche" && x.time ? el("button", { class: "btn btn-sm", type: "button", onclick: () => {
          const t = prompt("¿A qué hora se hace la copia y el despliegue de cada noche? (HH:MM)", x.time);
          if (t && t.trim() !== x.time) cronOp({ id: "noche", op: "time", time: t.trim() });
        } }, x.time) : null,
        !x.present ? null : x.paused
          ? el("button", { class: "btn btn-sm btn-primary", type: "button", onclick: () => cronOp({ id: x.id, op: "resume" }) }, "Reanudar")
          : el("button", { class: "btn btn-sm", type: "button", onclick: () => cronOp({ id: x.id, op: "pause" }, `¿Pausar «${x.title}»?\n\n${x.risk}`) }, "Pausar")));
  });
  const err = c.errors?.size ? el("div", { class: "cl-foot" }, el("span", {}, `Último error de una tarea: ${c.errors.at ? fmtAgo(c.errors.at) : "?"} (detalle en ~/.local/state/clientes/cron.err)`)) : null;
  put(box, rows, err);
}

/* ---------------------------------------------------------------- registro */

function renderEvents() {
  const box = $("cl-events"), ev = S.ev;
  if (!ev) return;
  if (ev.failed) return box.replaceChildren(empty(`No se pudo leer: ${ev.failed}`));
  for (const b of document.querySelectorAll("#cl-ev-filter .seg-btn")) b.classList.toggle("active", b.dataset.f === evFilter);
  let list = ev.events;
  if (evFilter === "main") list = list.filter((e) => (e.level || e.pushed || e.text.startsWith("===")) && !e.text.startsWith("DNS "));
  if (!list.length) return box.replaceChildren(empty("Nada todavía."));
  const shown = evMore ? list : list.slice(0, 15);
  put(box, shown.map((e) => el("div", { class: "cl-row cl-ev" },
    el("span", { class: "cl-ev-time" }, e.at ? when(e.at) : ""),
    el("div", { class: `cl-ev-text ${e.level ? `cl-${e.level}` : ""}` }, e.text, e.pushed ? el("span", { class: "muted small", title: "Se te avisó al móvil (ntfy)" }, "  📱") : null,
      evFilter === "all" && e.more.length ? el("pre", { class: "cl-ev-more" }, e.more.join("\n")) : null))),
    list.length > shown.length ? el("button", { class: "cl-more", type: "button", onclick: () => { evMore = true; renderEvents(); } }, `Ver ${list.length - shown.length} más`) : null);
}

/* ---------------------------------------------------------------- widget de Estado */

export async function loadCard() {
  const b = $("cl-card-badge");
  if (!b) return;
  try {
    const st = await api("/api/clientes?soft=1");
    const up = st.projects.filter((p) => p.ok).length;
    b.textContent = st.level === "ok" ? "Bien" : st.level === "warn" ? "Atención" : "Problema";
    b.className = `badge ${st.level}`;
    $("cl-card-value").textContent = st.mode === "casa" ? "🏠 En casa" : st.mode === "vm" ? "☁ En la VM" : "?";
    $("cl-card-sub").textContent = st.problems[0] || `${up} de ${st.projects.length} responden · copia ${st.backup_at ? fmtAgo(st.backup_at) : "–"}`;
  } catch (e) {
    if (e.message === "no autenticado") return;
    b.textContent = "Sin datos";
    b.className = "badge";
    $("cl-card-sub").textContent = e.message;
  }
}

/* ---------------------------------------------------------------- ciclo de la vista */

export function init() {
  initSheet();
  $("cl-refresh").onclick = () => { loadStatus(); loadRest(true); toast("Comprobando…"); };
  $("cl-new").onclick = newForm;
  $("cl-job").onclick = () => watchJob("/api/clientes/job", S.st?.job?.name || "En marcha", DONE, () => { jobWas = false; loadStatus(); loadRest(true); });
  for (const b of document.querySelectorAll("#cl-ev-filter .seg-btn")) b.onclick = () => { evFilter = b.dataset.f; evMore = false; renderEvents(); };
}

export function show() {
  loadStatus();
  loadRest();
}

export function hide() {
  clearTimeout(timer);
}

export function leave() {
  clearTimeout(timer);
  closeSheet();
  closeRunner();
}
