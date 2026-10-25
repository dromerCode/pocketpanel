import shlex

from ...requirements import PRELUDE, chk


def script(v: dict) -> tuple[str, dict]:
    dev = shlex.quote(v["device"])
    body = (PRELUDE + chk("device", "error", f"test -e {dev} || {{ echo no existe {dev}; exit 1; }}")
            + chk("mdadm", "warn", "command -v mdadm") + chk("smartctl", "warn", "command -v smartctl"))
    labels = {"device": "El dispositivo existe", "mdadm": "mdadm instalado",
              "smartctl": "smartctl instalado (para ver la salud de los discos)"}
    if v.get("ssh"):
        ssh = " ".join(x for x in ["ssh -o ConnectTimeout=5 -o BatchMode=yes", v.get("ssh_options") or "",
                                   shlex.quote(v["ssh"]), "sh -s"] if x)
        return f"{ssh} <<'PP_EOF'\n{body}PP_EOF\n", labels
    return body, labels
