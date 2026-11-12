from ...module import Module, field

MODULE = Module(
    icon="☁", title="Clientes",
    desc="Las webs de clientes que sirves desde una VM con relevo en casa: dónde están servidas, la VM, las copias, "
         "los despliegues, el DNS y las tareas programadas, y sus acciones (pasar a casa, restaurar, alta y baja de "
         "proyectos). Necesita los scripts de ~/bin/clientes en este servidor.",
    order=97,
    fields=[
        field("script", "Script del panel", default="~/bin/clientes/panel.sh", required=True,
              help="El script que lee el estado y lanza las acciones."),
    ],
)
