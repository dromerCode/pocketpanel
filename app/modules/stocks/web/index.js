// Bolsa: su pestaña (#stocks) y una tarjeta en Estado con lo que vale la cartera.
import * as view from "./stocks.js";

export default {
  styles: ["style.css"],
  view: { html: "view.html", tab: { icon: "↗", label: "Bolsa", order: 25 } },
  cards: [{ slot: "right", html: "card.html", order: 5, show: view.loadCard, slow: view.loadCard }],
  tour: [{ sel: '.tabbar a[data-tab="stocks"]', title: "Bolsa",
    text: "Tu cartera, lo que sigues y qué hacer con cada valor según sus indicadores." }],
  init: view.init,
  show: view.show,
  hide: view.hide,
};
