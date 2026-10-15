// Asistente de la primera vez: lo pide todo (nombre, PIN, módulos…) sin tocar archivos.
import { el, toast } from "./api.js";
import { field, renderChecks, switchInput } from "./modules.js";

const $ = (id) => document.getElementById(id);
const state = { code: "", info: null, name: "", timezone: "", pin: "", pin2: "", modules: {}, step: 0 };
let installPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; });

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify(body), credentials: "same-origin" });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `error ${r.status}`);
  return data;
}

async function loadInfo(code) {
  const r = await fetch(`/api/setup?code=${encodeURIComponent(code)}`, { credentials: "same-origin" });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `error ${r.status}`);
  return data;
}

/* ---------- Pasos ---------- */

function stepWelcome() {
  const code = el("input", { class: "setup-input mono", placeholder: "ABC-123", autocapitalize: "characters",
    autocomplete: "off", "aria-label": "Código de instalación" });
  code.value = state.code;
  const needCode = !state.info;
  return {
    body: el("div", { class: "setup-hero" },
      el("img", { src: "/icon.svg", alt: "", class: "setup-logo" }),
      el("h1", {}, "pocketpanel"),
      el("p", { class: "setup-lead" }, "Tu servidor, en el bolsillo."),
      el("p", { class: "muted" }, "Vamos a dejarlo listo en un par de minutos: nombre, PIN y lo que quieres usar. Sin tocar ningún archivo."),
      needCode ? el("label", { class: "setup-field" }, "Código de instalación (te lo enseñó ./install.sh)", code) : null),
    next: "Empezar",
    async go() {
      if (!needCode) return true;
      state.code = code.value.trim();
      state.info = await loadInfo(state.code);
      prefill();
      return true;
    },
  };
}

function prefill() {
  const i = state.info;
  state.name = state.name || i.hostname || i.name || "servidor";
  state.timezone = state.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || i.timezone;
  for (const m of i.modules) state.modules[m.name] ??= { enabled: m.enabled, values: { ...m.values } };
}

function stepServer() {
  const name = el("input", { class: "setup-input", value: state.name, maxlength: 40 });
  const zones = Intl.supportedValuesOf ? Intl.supportedValuesOf("timeZone") : [state.timezone];
  const tz = el("select", { class: "setup-input" }, zones.map((z) => el("option", { value: z }, z.replace(/_/g, " "))));
  tz.value = state.timezone;
  return {
    title: "Tu servidor", lead: "Cómo se llamará en la app y en los avisos.",
    body: el("div", { class: "setup-form" },
      el("label", { class: "setup-field" }, "Nombre", name),
      el("label", { class: "setup-field" }, "Zona horaria (para las tareas de cada día)", tz)),
    async go() {
      if (!name.value.trim()) throw new Error("ponle un nombre");
      state.name = name.value.trim();
      state.timezone = tz.value;
      return true;
    },
  };
}

function stepPin() {
  const mk = (v, label) => el("input", { class: "setup-input setup-pin mono", type: "password", inputmode: "numeric",
    autocomplete: "new-password", maxlength: 12, value: v, "aria-label": label });
  const a = mk(state.pin, "PIN"), b = mk(state.pin2, "Repite el PIN");
  return {
    title: "Tu PIN", lead: "Es la llave del panel: con él se entra a la terminal y a Docker. Mejor de 6 números o más.",
    body: el("div", { class: "setup-form" },
      el("label", { class: "setup-field" }, "PIN", a), el("label", { class: "setup-field" }, "Repítelo", b)),
    async go() {
      if (!/^\d{4,12}$/.test(a.value)) throw new Error("el PIN tiene que tener de 4 a 12 números");
      if (a.value !== b.value) throw new Error("los dos PIN no coinciden");
      state.pin = a.value;
      state.pin2 = b.value;
      return true;
    },
  };
}

function moduleCard(m) {
  const st = state.modules[m.name];
  const sw = switchInput(st.enabled);
  const fields = m.fields.map((f) => [f.key, field(f, st.values[f.key])]);
  const checks = el("div", {});
  const extra = el("div", { class: "setup-mod-extra" },
    fields.length ? el("div", { class: "form" }, fields.map(([, f]) => f.node)) : null,
    el("div", { class: "btn-row" }, el("button", { class: "btn btn-sm", type: "button", onclick: runChecks }, "Comprobar requisitos")),
    checks);
  const collect = () => {
    st.enabled = sw.input.checked;
    for (const [k, f] of fields) st.values[k] = f.get();
  };
  async function runChecks() {
    collect();
    checks.replaceChildren(el("p", { class: "muted small" }, "Comprobando en el servidor…"));
    try {
      renderChecks(checks, await post(`/api/setup/check/${m.name}`, { code: state.code, values: st.values }));
    } catch (e) {
      checks.replaceChildren(el("p", { class: "form-error" }, e.message));
    }
  }
  const node = el("div", { class: `setup-mod ${st.enabled ? "on" : ""}` },
    el("label", { class: "setup-mod-head" },
      el("span", { class: "mod-icon" }, m.icon),
      el("span", { class: "setup-mod-text" }, el("b", {}, m.title), el("span", { class: "muted small" }, m.desc)),
      sw.node),
    extra);
  sw.input.addEventListener("change", () => { node.classList.toggle("on", sw.input.checked); collect(); });
  return { node, collect };
}

function stepModules() {
  const cards = state.info.modules.map(moduleCard);
  return {
    title: "¿Qué quieres usar?", lead: "Activa lo que te sirva; lo demás se puede encender luego desde ⚙ Módulos.",
    body: el("div", { class: "setup-mods" }, cards.map((c) => c.node)),
    async go() { cards.forEach((c) => c.collect()); return true; },
  };
}

function stepPush() {
  const ok = window.isSecureContext && "PushManager" in window;
  return {
    title: "Avisos en el móvil", lead: "pocketpanel te avisa si se para un contenedor, se llena un disco o falla un backup.",
    body: el("div", { class: "setup-card" },
      el("div", { class: "setup-big" }, "🔔"),
      ok ? el("p", {}, "Al terminar, en el tutorial, te enseño la campana para activarlos con un toque.")
        : el("p", {}, "Para recibir avisos hay que abrir la app por HTTPS (la dirección .ts.net:8443 de Tailscale). Si ahora no lo estás, actívalos luego desde ahí con la campana 🔕.")),
  };
}

function stepInstall() {
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const standalone = matchMedia("(display-mode: standalone)").matches;
  let body;
  if (standalone) body = el("p", {}, "Ya la tienes instalada. 👌");
  else if (installPrompt) {
    body = el("div", {}, el("p", {}, "Instálala como una app más: se abre a pantalla completa y con su icono."),
      el("button", { class: "btn btn-primary", type: "button", onclick: async () => {
        installPrompt.prompt();
        await installPrompt.userChoice;
        installPrompt = null;
      } }, "Instalar en este dispositivo"));
  } else if (ios) {
    body = el("ol", { class: "setup-steps" }, el("li", {}, "Toca el botón Compartir (el cuadrado con la flecha)."),
      el("li", {}, "Elige «Añadir a pantalla de inicio»."), el("li", {}, "Ábrela desde su icono."));
  } else {
    body = el("ol", { class: "setup-steps" }, el("li", {}, "Abre el menú del navegador (⋮)."),
      el("li", {}, "Elige «Instalar aplicación» o «Añadir a pantalla de inicio»."), el("li", {}, "Ábrela desde su icono."));
  }
  return { title: "Ponla en tu pantalla de inicio", lead: "Así la tienes a un toque, como cualquier app.",
    body: el("div", { class: "setup-card" }, el("div", { class: "setup-big" }, "📱"), body) };
}

function stepDone() {
  const on = state.info.modules.filter((m) => state.modules[m.name].enabled);
  return {
    title: "¡Todo listo!", lead: "Esto es lo que vas a tener:",
    body: el("div", { class: "setup-card" },
      el("p", {}, el("b", {}, state.name), ` · ${state.timezone}`),
      el("ul", { class: "setup-summary" }, on.map((m) => el("li", {}, `${m.icon}  ${m.title}`))),
      el("p", { class: "muted small" }, "Al terminar se guarda todo, el panel se reinicia unos segundos y te enseño cómo funciona.")),
    next: "Terminar",
    async go() {
      await post("/api/setup", { code: state.code, name: state.name, timezone: state.timezone, pin: state.pin,
        modules: state.modules });
      return "done";
    },
  };
}

const STEPS = [stepWelcome, stepServer, stepPin, stepModules, stepPush, stepInstall, stepDone];
let current = null;

function render() {
  const s = STEPS[state.step]();
  current = s;
  $("setup-bar").style.width = `${(state.step / (STEPS.length - 1)) * 100}%`;
  const head = s.title ? [el("h2", { class: "setup-title" }, s.title), s.lead ? el("p", { class: "setup-lead" }, s.lead) : null] : [];
  const err = el("p", { class: "form-error", id: "setup-error", role: "alert" });
  const box = el("div", { class: "setup-anim" }, ...head, s.body, err);
  $("setup-step").replaceChildren(box);
  $("setup-back").style.visibility = state.step ? "visible" : "hidden";
  $("setup-next").textContent = s.next || "Siguiente";
  $("setup-step").scrollTop = 0;
  box.querySelector("input")?.focus({ preventScroll: true });
}

async function next() {
  const btn = $("setup-next");
  btn.disabled = true;
  $("setup-error").textContent = "";
  try {
    const r = current.go ? await current.go() : true;
    if (r === "done") return finish();
    state.step = Math.min(state.step + 1, STEPS.length - 1);
    render();
  } catch (e) {
    $("setup-error").textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

async function finish() {
  $("setup-step").replaceChildren(el("div", { class: "setup-hero setup-anim" },
    el("span", { class: "spinner setup-spinner" }), el("h2", { class: "setup-title" }, "Preparando tu panel…"),
    el("p", { class: "muted" }, "Se está reiniciando con tu configuración.")));
  document.querySelector(".setup-nav").hidden = true;
  await new Promise((r) => setTimeout(r, 2500));
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch("/api/me", { credentials: "same-origin", cache: "no-store" });
      if (r.ok) { location.replace("/#tour"); location.reload(); return; }
    } catch { /* arrancando */ }
    await new Promise((r) => setTimeout(r, 1000));
  }
  toast("Tarda más de la cuenta: recarga la página en un momento", true);
}

export async function startSetup() {
  document.getElementById("login").hidden = true;
  document.getElementById("app").hidden = true;
  $("setup").hidden = false;
  const m = location.hash.match(/^#setup\/([A-Za-z0-9-]+)/);
  if (m) {
    state.code = m[1];
    try {
      state.info = await loadInfo(state.code);
      prefill();
      history.replaceState(null, "", "/#setup");  // que el código no se quede en la barra
    } catch (e) {
      toast(e.message, true);
    }
  }
  $("setup-back").onclick = () => { state.step = Math.max(0, state.step - 1); render(); };
  $("setup-next").onclick = next;
  render();
}
