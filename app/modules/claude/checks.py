import shlex

from ...requirements import PRELUDE, chk


def script(v: dict) -> tuple[str, dict]:
    home = shlex.quote(v["home"]) if v.get("home") else '"$HOME"'
    cwd = shlex.quote(v["cwd"]) if v.get("cwd") else home
    if v.get("bin"):
        bin_ = shlex.quote(v["bin"])
    elif v.get("home"):
        bin_ = shlex.quote(f"{v['home']}/.local/bin/claude")
    else:
        bin_ = '"$HOME/.local/bin/claude"'
    s = (PRELUDE + chk("bin", "error", f"test -x {bin_} || {{ echo no está {bin_}; exit 1; }}; "
                                       f"HOME={home} {bin_} --version")
         + chk("cwd", "error", f"test -d {cwd} || {{ echo no existe {cwd}; exit 1; }}"))
    return s, {"bin": "claude instalado y funcionando", "cwd": "La carpeta de trabajo existe"}
