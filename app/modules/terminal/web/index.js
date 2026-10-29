// Terminal: pestaña con una shell (o tmux) en el host. xterm.js (en vendor/, servido por el propio panel: no depende de
// que el móvil llegue a una CDN) solo se descarga si este módulo está activo.
import * as terminal from "./terminal.js";

export default {
  styles: ["vendor/xterm.css", "style.css"],
  scripts: ["vendor/xterm.js", "vendor/addon-fit.js"],
  view: { html: "view.html", tab: { icon: "›_", label: "Terminal", order: 10 } },
  tour: [{ sel: '.tabbar a[data-tab="terminal"]', title: "Terminal",
    text: "Una shell en el servidor desde el móvil, con teclas extra (Esc, Ctrl, flechas…)." }],
  init: terminal.init,
  show: terminal.show,
};
