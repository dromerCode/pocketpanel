from ...module import Module, field

MODULE = Module(
    icon="€", title="Cobros",
    desc="Lo que te deben tus clientes: sus suscripciones a tus programas, encargos con pagos a plazos y apuntes "
         "sueltos. Saca cada cuota sola, apunta lo que vas cobrando y rellena tu plantilla de factura (.xlsx). "
         "No cobra ni envía nada.",
    order=80,
    fields=[
        field("iva", "IVA (%)", default="21"),
        field("irpf", "Retención IRPF por defecto (%)", default="7",
              help="La que se pone a un cliente nuevo. A los particulares, 0."),
        field("due_days", "Días para pagar", "int", default=15,
              help="Desde la fecha de la cuota o de la factura. Pasados, sale como vencida."),
        field("lead_days", "Sacar la cuota con antelación (días)", "int", default=7,
              help="Para poder cobrarla antes de que empiece el periodo."),
        field("iban", "Tu IBAN", help="Para «Forma de pago» en las facturas por transferencia."),
        field("alerts", "Avisar de cuotas nuevas y vencidas", "bool", default=True),
    ],
)
