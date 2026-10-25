from ...module import Module, field

MODULE = Module(
    icon="⬆", title="Actualizaciones",
    desc="Busca imágenes nuevas cada día y actualiza contenedores con vuelta atrás si fallan.",
    enabled=True, order=30,
    after=("backups",),  # hace una copia antes de actualizar si los backups están activos
    fields=[field("check_at", "Buscar cada día a las", "time", default="05:30")],
)
