// Archivos: su pestaña (#files/<ruta>), con portapapeles para copiar/cortar y pegar entre carpetas.
import * as view from "./files.js";

export default {
  styles: ["style.css"],
  view: { html: "view.html", tab: { icon: "❐", label: "Archivos", order: 15 } },
  tour: [{ sel: '.tabbar a[data-tab="files"]', title: "Archivos",
    text: "Los archivos del servidor: copia, corta y pega entre carpetas, sube, descarga, renombra o edita un texto." }],
  init: view.init,
  show: view.show,
  hide: view.hide,
};
