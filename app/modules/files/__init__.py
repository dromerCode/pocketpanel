from ...module import Module, field

MODULE = Module(
    icon="❐", title="Archivos",
    desc="Gestor de archivos del servidor: navegar, copiar y pegar, mover, renombrar, borrar, subir y descargar "
         "(carpetas como .tar). Va por el mismo SSH que el resto: ve lo que puede ver el usuario del host.",
    order=55,
    fields=[
        field("roots", "Carpetas de inicio", "list", default=["~"],
              help="Lo único que se puede ver y tocar (y lo de dentro). ~ es la carpeta personal; p. ej. ~ y /mnt."),
    ],
)
