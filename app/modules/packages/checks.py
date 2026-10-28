from ...requirements import PRELUDE, chk


def script(v: dict) -> tuple[str, dict]:
    body = (PRELUDE + chk("apt", "error", "command -v apt")
            + chk("update", "error", "sudo -n -l /usr/bin/apt update")
            + chk("upgrade", "error", "sudo -n -l /usr/bin/apt upgrade -y"))
    rule = "usuario ALL=(root) NOPASSWD: /usr/bin/apt update, /usr/bin/apt upgrade -y"
    return body, {"apt": "Es un sistema con apt (Debian, Ubuntu…)",
                  "update": f"Puede hacer «sudo apt update» sin contraseña (en sudoers: {rule})",
                  "upgrade": "Puede hacer «sudo apt upgrade -y» sin contraseña"}
