from ...module import Module, field

MODULE = Module(
    icon="◎", title="Webs y certificados",
    desc="Comprueba que tus webs responden y avisa si caen o si el certificado está a punto de caducar.",
    order=70,
    fields=[
        field("urls", "Webs a vigilar", "list", "Una URL por línea: https://midominio.com, http://127.0.0.1:8096…"),
        field("interval", "Comprobar cada (minutos)", "int", default=5),
        field("cert_warn_days", "Avisar si al certificado le quedan (días)", "int", default=14),
    ],
)
