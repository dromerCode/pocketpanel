from ...module import Module, field

MODULE = Module(
    icon="✳", title="Claude Code",
    desc="Chat con el Claude Code del servidor, botón de diagnóstico y resumen diario por push.",
    order=40,
    fields=[
        field("home", "HOME de Claude", help="Vacío = el de tu usuario"),
        field("cwd", "Carpeta de trabajo", help="Vacío = igual que el HOME"),
        field("bin", "Ruta de claude", help="Vacío = HOME/.local/bin/claude (mírala con `which claude`)"),
        field("permission_mode", "Permisos", "choice", "El chat no puede preguntarte: con «auto» o «bypassPermissions» "
              "puede ejecutar comandos", choices=["", "default", "acceptEdits", "plan", "auto", "dontAsk",
                                                   "bypassPermissions"]),
        field("report_at", "Resumen diario a las", "time", "Vacío = sin resumen diario", default="09:00",
              nullable=True),
        field("report_notes", "Notas para el resumen", help="Cosas que Claude debe saber al revisar"),
        field("diagnosis", "Prompt del diagnóstico", help="Vacío = uno genérico"),
    ],
)
