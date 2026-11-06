from ...module import Module, field

MODULE = Module(
    icon="✉", title="ntfy",
    desc="Los mensajes de uno o varios temas de ntfy en un widget de Estado. Los temas se añaden desde el propio widget.",
    order=75,
    fields=[
        field("server", "Servidor", default="https://ntfy.sh", required=True,
              help="https://ntfy.sh o la URL del tuyo"),
        field("token", "Token de acceso", "secret", "Solo si tus temas están protegidos (tk_…)"),
        field("notify", "Avisar en el móvil de cada mensaje nuevo", "bool",
              help="Con esto el panel mira cada 30 s; sin ello, cada 10 min (y al abrir Estado)"),
    ],
)
