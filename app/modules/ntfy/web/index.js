// ntfy: los mensajes de los temas que sigues, en Estado.
import { initNtfy, loadNtfy } from "./ntfy.js";

export default {
  styles: ["style.css"],
  cards: [{ slot: "right", html: "card.html", order: 5, title: "ntfy", init: initNtfy, show: () => loadNtfy(), slow: () => loadNtfy() }],
};
