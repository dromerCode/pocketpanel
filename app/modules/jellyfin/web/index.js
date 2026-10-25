// Usuarios de Jellyfin (jfa-go): pestaña con cuentas, sesiones activas e invitaciones.
import * as users from "./users.js";

export default {
  styles: ["style.css"],
  view: { html: "view.html", name: "users", tab: { icon: "☺", label: "Usuarios", order: 20 } },
  tour: [{ sel: '.tabbar a[data-tab="users"]', title: "Usuarios", text: "Cuentas e invitaciones de Jellyfin." }],
  init: users.init,
  show: users.show,
  leave: users.leave,
};
