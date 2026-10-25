// Terminal: pestaña con una shell (o tmux) en el host. xterm.js solo se descarga si este módulo está activo.
import * as terminal from "./terminal.js";

export default {
  styles: ["https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.css", "style.css"],
  scripts: ["https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.js",
    "https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.js"],
  view: { html: "view.html", tab: { icon: "›_", label: "Terminal", order: 10 } },
  tour: [{ sel: '.tabbar a[data-tab="terminal"]', title: "Terminal",
    text: "Una shell en el servidor desde el móvil, con teclas extra (Esc, Ctrl, flechas…)." }],
  init: terminal.init,
  show: terminal.show,
};
