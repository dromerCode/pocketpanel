// Pequeño cliente de la API. Un 401 en cualquier llamada devuelve a la pantalla de login.
let onUnauthorized = () => {};

// Lo que devuelve /api/me: nombre del servidor y módulos activos (con sus datos).
export const panel = { name: "", modules: [] };
export const has = (m) => panel.modules.includes(m);
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

export async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body ? { "content-type": "application/json" } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin",
  });
  if (res.status === 401) {
    onUnauthorized();
    throw new Error("no autenticado");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `error ${res.status}`);
  return data;
}

export function wsUrl(path) {
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;
}

let toastTimer;
export function toast(msg, bad = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.toggle("bad", bad);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 3500);
}

/** Copia texto al portapapeles; false si no se ha podido. navigator.clipboard solo existe con HTTPS (o en
 * localhost): por http://IP:puerto se copia a la antigua, con un textarea seleccionado y execCommand. */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch { /* sin HTTPS no hay API */ }
  const ta = el("textarea", { readonly: "", style: "position:fixed;top:0;left:0;opacity:0" });
  ta.value = text;
  const back = document.activeElement;
  document.body.append(ta);
  ta.select();
  ta.setSelectionRange(0, text.length);  // iOS no selecciona con select() solo
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { /* nada */ }
  ta.remove();
  back?.focus?.({ preventScroll: true });
  return ok;
}

export function fmtBytes(n) {
  if (n == null) return "–";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n >= 100 || i === 0 ? Math.round(n) : n.toFixed(1)} ${u[i]}`;
}

export function fmtUptime(s) {
  if (s == null) return "";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

export function fmtAgo(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "ahora";
  if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
  if (s < 86400) return `hace ${Math.floor(s / 3600)} h`;
  if (s < 86400 * 7) return `hace ${Math.floor(s / 86400)} d`;
  return new Date(ts * 1000).toLocaleDateString("es-ES", { day: "numeric", month: "short" });
}

export function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null) n.append(c);
  return n;
}

// Icono de servicio: imagen con inicial de respaldo si no carga.
export function serviceIcon(target, svc) {
  target.replaceChildren();
  const letter = (svc.title || svc.name || "?")[0].toUpperCase();
  if (!svc.icon) { target.textContent = letter; return; }
  const img = el("img", { src: svc.icon, alt: "", loading: "lazy" });
  img.onerror = () => { target.textContent = letter; };
  target.append(img);
}
