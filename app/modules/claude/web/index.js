// Claude: pestaña de chat con el Claude Code del servidor. marked y DOMPurify (en vendor/, servidos por el propio panel:
// el móvil no siempre llega a una CDN) solo se descargan al abrir esta pestaña.
import * as claude from "./claude.js";

export default {
  styles: ["style.css"],
  scripts: ["vendor/marked.min.js", "vendor/purify.min.js"],
  view: { html: "view.html", tab: { icon: "✳", label: "Claude", order: 30 } },
  tour: [{ sel: '.tabbar a[data-tab="claude"]', title: "Claude",
    text: "Pregúntale a tu servidor qué le pasa. El botón 🩺 hace un diagnóstico completo." }],
  init: claude.init,
  show: claude.show,
};
