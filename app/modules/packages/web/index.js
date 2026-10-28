// Paquetes del sistema (apt): un widget en Estado.
import { loadPackages } from "./packages.js";

export default {
  styles: ["style.css"],
  cards: [{ slot: "left", html: "card.html", order: 4, title: "Paquetes", show: () => loadPackages(), slow: () => loadPackages() }],
};
