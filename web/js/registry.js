// Interfaz de los módulos: solo se descarga la de los activos. Cada uno tiene app/modules/<nombre>/web/index.js
// (servido en /modules/<nombre>/), que exporta por defecto lo que aporta. Todo es opcional:
//
//   styles:  ["style.css"]                    su CSS (rutas relativas a su carpeta web/)
//   scripts: ["https://cdn…/lib.js"]          <script> clásicos que necesita, en orden (xterm, marked…)
//   view:    { html: "view.html", name?, tab?: { icon, label, order? } }
//            una vista en #<name> (por defecto, el nombre del módulo); con `tab`, además, sale en la barra
//   cards:   [{ slot: "left" | "right" | "bottom", html: "card.html", order?, size?, title?, init?, show?, fast?, slow? }]
//            widgets en Estado: init una vez, show al entrar, fast cada 5 s y slow cada 30 s. `slot` y `order`
//            dicen dónde salen la primera vez y `size` su ancho (3, 4, 6, 8 o 12 de 12 columnas); luego cada
//            cual los mueve y los ensancha desde «Organizar» (widgets.js)
//   tour:    [{ sel, title, text }]            sus pasos del tutorial
//   init()                                     una vez al arrancar (p. ej. para engancharse a Servicios)
//   show(args) / hide() / leave()              el ciclo de su vista, como las del núcleo
import { toast } from "./api.js";

// Dónde cae por defecto cada tarjeta en Estado según su `slot` (el usuario luego la mueve y la ensancha a su gusto):
// left = tras el historial, right = tras los discos, bottom = al final a lo ancho
const SLOT_RANK = { left: 30, right: 60, bottom: 90 };
const SLOT_SIZE = { left: 6, right: 6, bottom: 12 };

export const loaded = [];   // [{ name, def, base, order }] en el orden de la tienda
const scripts = new Map();  // url → promesa: cada librería se carga una vez aunque la pidan dos módulos

function loadScript(src) {
  if (!scripts.has(src)) {
    scripts.set(src, new Promise((ok, bad) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = ok;
      s.onerror = () => bad(new Error(`no se pudo cargar ${src}`));
      document.head.append(s);
    }));
  }
  return scripts.get(src);
}

function loadStyle(href) {
  return new Promise((ok) => {
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    l.onload = l.onerror = ok;  // sin su CSS el módulo funciona igual
    document.head.append(l);
  });
}

async function fragment(url) {
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) throw new Error(`${url}: error ${r.status}`);
  return document.createRange().createContextualFragment(await r.text());
}

async function loadOne(name, order) {
  const base = `/modules/${name}/`;
  const def = (await import(`${base}index.js`)).default || {};
  await Promise.all((def.styles || []).map((s) => loadStyle(new URL(s, location.origin + base))));
  for (const s of def.scripts || []) await loadScript(new URL(s, location.origin + base).href);
  const html = {};
  if (def.view?.html) html.view = await fragment(base + def.view.html);
  html.cards = await Promise.all((def.cards || []).map((c) => (c.html ? fragment(base + c.html) : null)));
  return { name, def, base, order, html };
}

function mount(m) {
  const { def, html } = m;
  if (html.view) document.querySelector("#app > nav.tabbar").before(html.view);
  (def.cards || []).forEach((c, i) => {
    const grid = document.getElementById("st-grid");
    const box = document.createElement("div");
    const slot = c.slot || "bottom";
    box.className = "w";
    box.dataset.w = def.cards.length > 1 ? `${m.name}-${i + 1}` : m.name;
    box.dataset.size = c.size ?? SLOT_SIZE[slot];
    box.dataset.rank = SLOT_RANK[slot] + Number(c.order ?? m.order) / 1000;
    if (html.cards[i]) box.append(html.cards[i]);
    box.dataset.title = c.title || box.querySelector(".section-title")?.textContent.trim() || m.name;
    const after = [...grid.children].find((x) => Number(x.dataset.rank) > Number(box.dataset.rank));
    grid.insertBefore(box, after || null);
  });
  const tab = def.view?.tab;
  if (tab) {
    const name = def.view.name || m.name;
    const a = document.createElement("a");
    a.href = `#${name}`;
    a.dataset.tab = name;
    a.dataset.order = tab.order ?? m.order;
    const ico = document.createElement("span");
    ico.className = "tab-ico";
    ico.textContent = tab.icon;
    a.append(ico, tab.label);
    const bar = document.querySelector(".tabbar");
    const after = [...bar.children].find((x) => x.dataset.order && Number(x.dataset.order) > Number(a.dataset.order));
    bar.insertBefore(a, after || null);
  }
}

/** Carga y monta la interfaz de los módulos activos que la tienen (/api/me → ui), en paralelo: si uno falla,
 * los demás siguen. */
export async function loadModules(names) {
  const results = await Promise.allSettled(names.map((n, i) => loadOne(n, i)));
  results.forEach((r, i) => {
    if (r.status === "fulfilled") {
      mount(r.value);
      loaded.push(r.value);
    } else {
      console.warn(`módulo ${names[i]}:`, r.reason);
      toast(`No se pudo cargar el módulo ${names[i]}: ${r.reason?.message || r.reason}`, true);
    }
  });
}

/** Vistas que aportan los módulos: { nombre: def }. */
export function moduleViews() {
  return Object.fromEntries(loaded.filter((m) => m.def.view).map((m) => [m.def.view.name || m.name, m.def]));
}

export const cards = () => loaded.flatMap((m) => m.def.cards || []);
export const tourSteps = () => loaded
  .slice().sort((a, b) => (a.def.view?.tab?.order ?? 1000 + a.order) - (b.def.view?.tab?.order ?? 1000 + b.order))
  .flatMap((m) => m.def.tour || []);
