// Claude: pestaña de chat con el Claude Code del servidor. marked y DOMPurify solo se descargan con este módulo.
import * as claude from "./claude.js";

export default {
  styles: ["style.css"],
  scripts: ["https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js",
    "https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js"],
  view: { html: "view.html", tab: { icon: "✳", label: "Claude", order: 30 } },
  tour: [{ sel: '.tabbar a[data-tab="claude"]', title: "Claude",
    text: "Pregúntale a tu servidor qué le pasa. El botón 🩺 hace un diagnóstico completo." }],
  init: claude.init,
  show: claude.show,
};
