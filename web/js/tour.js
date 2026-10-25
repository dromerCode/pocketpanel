// Tutorial: oscurece la pantalla y va iluminando cada parte con una explicación.
import { tourSteps } from "./registry.js";

const $ = (id) => document.getElementById(id);

function steps() {
  const tab = (t) => `.tabbar a[data-tab="${t}"]`;
  return [
    { sel: "#view-status .cards", title: "Tu servidor de un vistazo",
      text: "CPU, RAM, temperatura y contenedores en marcha. Toca «Contenedores» para ir a ellos." },
    { sel: "#charts", title: "Historial", text: "Cómo ha ido la última hora, el último día o la última semana." },
    { sel: "#push-btn", title: "Avisos", text: "Actívalos aquí y te llegará una notificación si algo se para, se llena un disco o falla un backup.",
      action: ["Activar avisos", () => $("push-btn").click()] },
    { sel: 'a[href="#modules"]', title: "Módulos", text: "Aquí activas o configuras lo que quieras (backups, Claude, descargas…) y cambias el nombre del servidor. También puedes repetir este tutorial." },
    { sel: tab("services"), title: "Servicios", text: "Todos tus contenedores: arrancar, parar, reiniciar, ver logs y actualizarlos." },
    ...tourSteps(),  // los de los módulos activos, en el orden de sus pestañas
    { sel: null, title: "¡Ya está!", text: "Eso es todo. Si algún día te pierdes, lo tienes en ⚙ Módulos → «Ver el tutorial»." },
  ];
}

let list = [], i = 0;

function place() {
  const s = list[i];
  const target = s.sel && document.querySelector(s.sel);
  const hole = $("tour-hole"), bubble = $("tour-bubble");
  $("tour-title").textContent = s.title;
  $("tour-text").textContent = s.text;
  $("tour-count").textContent = `${i + 1}/${list.length}`;
  $("tour-next").textContent = i === list.length - 1 ? "Terminar" : "Siguiente";
  $("tour-extra").replaceChildren();
  if (s.action) {
    const b = document.createElement("button");
    b.className = "btn btn-sm";
    b.textContent = s.action[0];
    b.onclick = s.action[1];
    $("tour-extra").append(b);
  }
  if (!target || target.offsetParent === null) {
    hole.style.cssText = "left:50%;top:40%;width:0;height:0";
    bubble.style.cssText = "left:50%;top:40%;transform:translate(-50%,-50%)";
    return;
  }
  target.scrollIntoView({ block: "center", behavior: "instant" });
  const r = target.getBoundingClientRect(), pad = 6;
  hole.style.cssText = `left:${r.left - pad}px;top:${r.top - pad}px;width:${r.width + pad * 2}px;height:${r.height + pad * 2}px`;
  const bw = Math.min(340, innerWidth - 24);
  const left = Math.max(12, Math.min(innerWidth - bw - 12, r.left + r.width / 2 - bw / 2));
  const below = r.bottom + 14 + 170 < innerHeight;
  bubble.style.cssText = `width:${bw}px;left:${left}px;` + (below ? `top:${r.bottom + 14}px` : `bottom:${innerHeight - r.top + 14}px`);
}

function end() {
  $("tour").hidden = true;
  try { localStorage.setItem("pp-tour", "done"); } catch { /* sin almacenamiento: da igual */ }
  if (location.hash === "#tour") history.replaceState(null, "", "/#status");
}

export function startTour() {
  location.hash.startsWith("#tour") && history.replaceState(null, "", "/#status");
  dispatchEvent(new HashChangeEvent("hashchange"));
  list = steps();
  i = 0;
  $("tour").hidden = false;
  $("tour-next").onclick = () => (i < list.length - 1 ? (i++, place()) : end());
  $("tour-skip").onclick = end;
  setTimeout(place, 300);
  addEventListener("resize", () => !$("tour").hidden && place());
}
