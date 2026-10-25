from ...module import Module, field

MODULE = Module(
    icon="◫", title="RAID", desc="Estado de un RAID mdadm y SMART de sus discos, con avisos.",
    order=60,
    fields=[
        field("device", "Dispositivo", default="/dev/md0"),
        field("ssh", "En otra máquina", help="Vacío = en este servidor; si no, usuario@host"),
        field("ssh_options", "Opciones de SSH"),
        field("sudo", "Usar sudo para mdadm/smartctl", "bool", "Necesita una regla en sudoers"),
    ],
)
