// Cobros: lo que te deben tus clientes (pestaña #cobros) y un widget en Estado con el total.
import * as view from "./cobros.js";

export default {
  styles: ["style.css"],
  view: { html: "view.html", tab: { icon: "€", label: "Cobros", order: 27 } },
  cards: [{ slot: "right", html: "card.html", order: 6, title: "Cobros", show: view.loadCard }],
  tour: [{ sel: '.tabbar a[data-tab="cobros"]', title: "Cobros",
    text: "Tus clientes, sus suscripciones y lo que te deben. Apunta cada cobro y saca la factura con tu plantilla." }],
  init: view.init,
  show: view.show,
  hide: view.hide,
  leave: view.leave,
};
