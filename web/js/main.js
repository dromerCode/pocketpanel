import { api, has, panel, setUnauthorizedHandler } from "./api.js";
import * as status from "./status.js";
import * as services from "./services.js";
import * as terminal from "./terminal.js";
import * as claude from "./claude.js";
import * as users from "./users.js";
import * as modulesView from "./modules.js";
import * as downloads from "./downloads.js";
import { startSetup } from "./setup.js";
import { startTour } from "./tour.js";

const views = { status, services, terminal, users, claude, modules: modulesView, downloads };
const needs = { terminal: "terminal", users: "jellyfin", claude: "claude", downloads: "downloads" };  // vista → módulo
const enabled = (v) => !needs[v] || has(needs[v]);
let current = null;
let started = false;

function showLogin() {
  document.getElementById("app").hidden = true;
  document.getElementById("login").hidden = false;
  document.getElementById("pin").focus();
}

function route() {
  if (location.hash === "#tour") return startTour();
  const name = (location.hash.slice(1).split("/")[0]) || "status";
  const view = views[name] && enabled(name) ? name : "status";
  if (current && current !== view) { views[current].hide?.(); views[current].leave?.(); }
  for (const s of document.querySelectorAll(".view")) s.hidden = s.dataset.view !== view;
  for (const a of document.querySelectorAll(".tabbar a")) a.classList.toggle("active", a.dataset.tab === view);
  current = view;
  views[view].show?.(location.hash.slice(1).split("/").slice(1));
}

function applyModules(me) {
  Object.assign(panel, me);
  document.title = me.name;
  for (const n of document.querySelectorAll(".srv-name")) n.textContent = me.name;
  for (const n of document.querySelectorAll("[data-module]")) n.hidden = !has(n.dataset.module);
}

function start(me) {
  applyModules(me);
  document.getElementById("login").hidden = true;
  document.getElementById("app").hidden = false;
  if (!started) {
    started = true;
    for (const [name, v] of Object.entries(views)) if (enabled(name)) v.init?.();
    window.addEventListener("hashchange", route);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) views[current]?.hide?.();
      else views[current]?.show?.([]);
    });
  }
  route();
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const pin = document.getElementById("pin");
  const err = document.getElementById("login-error");
  err.textContent = "";
  try {
    await api("/api/login", { method: "POST", body: { pin: pin.value } });
    pin.value = "";
    start(await api("/api/me"));
  } catch (ex) {
    err.textContent = ex.message;
    pin.select();
  }
});

setUnauthorizedHandler(showLogin);
(async () => {
  // Primera vez (sin PIN todavía): asistente
  const setup = await fetch("/api/setup", { credentials: "same-origin" }).then((r) => r.json()).catch(() => ({}));
  if (setup.needed) return startSetup();
  api("/api/me").then(start).catch(() => showLogin());
})();

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
