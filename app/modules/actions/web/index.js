// Acciones rápidas: botones en Estado que ejecutan los comandos de actions.yml.
import { loadActions } from "./actions.js";

export default {
  styles: ["style.css"],
  cards: [{ slot: "bottom", html: "card.html", show: loadActions }],
};
