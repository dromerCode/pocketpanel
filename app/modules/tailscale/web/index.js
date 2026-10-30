// Tailscale: un widget en Estado con los dispositivos de la tailnet.
import { loadTailscale } from "./tailscale.js";

export default {
  styles: ["style.css"],
  cards: [{ slot: "right", html: "card.html", order: 6, show: loadTailscale, slow: loadTailscale }],
};
