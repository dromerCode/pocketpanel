from ...module import Module, field

MODULE = Module(
    icon="☺", title="Usuarios de Jellyfin", desc="Cuentas e invitaciones de Jellyfin a través de jfa-go.",
    order=90,
    fields=[
        field("jfa_url", "URL de jfa-go", default="http://127.0.0.1:8056"),
        field("jfa_user", "Usuario de jfa-go", "secret"),
        field("jfa_pass", "Contraseña de jfa-go", "secret"),
        field("jellyfin_url", "URL de Jellyfin", default="http://127.0.0.1:8096"),
        field("public_url", "Web pública de jfa-go", help="Para los enlaces de invitación"),
        field("db", "Ruta a jellyfin.db", help="Opcional: fechas de alta (necesita sqlite3)"),
    ],
)
