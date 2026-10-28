from ...module import Module

MODULE = Module(
    icon="⇪", title="Paquetes",
    desc="Los paquetes del sistema (apt) por actualizar, y actualizarlos desde Estado. Necesita poder usar "
         "«sudo apt update» y «sudo apt upgrade -y» sin contraseña.",
    order=35,
)
