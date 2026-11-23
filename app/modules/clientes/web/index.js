// Clientes: las webs de clientes (VM + relevo en casa) en su pestaña, y un resumen en Estado.
import * as view from "./clientes.js";

export default {
  styles: ["style.css"],
  view: { html: "view.html", tab: { icon: "☁", label: "Clientes", order: 28 } },
  cards: [{ slot: "right", html: "card.html", order: 7, title: "Clientes", show: view.loadCard, slow: view.loadCard }],
  tour: [{ sel: '.tabbar a[data-tab="clientes"]', title: "Clientes",
    text: "Dónde se sirven las webs de tus clientes, la VM, las copias, el DNS y las tareas programadas." }],
  init: view.init,
  show: view.show,
  hide: view.hide,
  leave: view.leave,
};
