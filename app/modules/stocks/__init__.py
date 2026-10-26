from ...module import Module, field

MODULE = Module(
    icon="↗", title="Bolsa",
    desc="Tu cartera de acciones: precios, recomendaciones por reglas, valores en seguimiento, «Descubrir» y avisos "
         "por Telegram cuando cambia algo. No compra ni vende nada: apunta lo que haces en tu bróker.",
    order=85,
    fields=[
        field("broker", "Bróker", default="Trade Republic", help="Solo para recordarte dónde operas."),
        field("max_positions", "Máximo de posiciones a la vez", "int", default=3),
        field("commission", "Comisión por operación (€)", default="1", help="Se descuenta del efectivo en cada compra y venta."),
        field("alerts", "Avisar cuando cambie una recomendación", "bool", default=True),
        field("alert_every", "Comprobar cada (minutos)", "int", default=30),
        field("digest_at", "Resumen diario a las", "time", default="07:00", nullable=True,
              help="Una foto por valor con su recomendación. Vacío: sin resumen."),
        field("telegram_chat", "Telegram: chat ID", help="El número de tu chat con el bot (p. ej. @userinfobot te lo dice)."),
        field("telegram_token", "Telegram: token del bot", "secret", help="El que te da @BotFather. Sin él, los avisos van solo por push."),
    ],
)
