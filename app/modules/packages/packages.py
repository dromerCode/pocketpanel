"""Los paquetes del sistema por actualizar (apt) y la actualización.

La lista sale de `apt list --upgradable`, que no necesita root y lee lo que bajó el último `apt update` (Ubuntu y
Debian lo hacen solos cada día). Actualizar es `sudo apt update` + `sudo apt upgrade -y`, justo esas órdenes, para
que baste con permitir esas dos en sudoers.

La actualización corre en el host desacoplada del panel (setsid + nohup) y escribe en un registro: si apt actualiza
Docker, el contenedor del panel se reinicia y su conexión SSH se corta, y eso no puede cortar a dpkg a medias. El
panel solo lee el registro, así que después de reiniciarse sigue viendo cómo va."""
import re
import time

DIR = "$HOME/.cache/pocketpanel"
LOG, PID = f"{DIR}/apt.log", f"{DIR}/apt.pid"
FRESH = 300  # s: la lista se relee como mucho cada 5 min (o al acabar una actualización)
LIST_SCRIPT = r"""
echo @list; LC_ALL=C apt list --upgradable 2>/dev/null
echo @stamp; stat -c %Y /var/lib/apt/periodic/update-success-stamp 2>/dev/null || stat -c %Y /var/cache/apt/pkgcache.bin
echo @reboot; [ -e /var/run/reboot-required ] && { echo yes; cat /var/run/reboot-required.pkgs 2>/dev/null; }
true
"""
RUNNING = f'[ -e "{PID}" ] && kill -0 "$(cat "{PID}")" 2>/dev/null'
LINE_RE = re.compile(r"^([^/\s]+)/(\S+)\s+(\S+)\s+(\S+)\s+\[upgradable from: ([^\]]+)\]")


class PackagesError(Exception):
    pass


def parse_list(out: str) -> dict:
    secs, cur = {}, None
    for line in out.splitlines():
        if line.startswith("@") and line[1:].strip().isalpha():
            cur = secs.setdefault(line[1:].strip(), [])
        elif cur is not None and line.strip():
            cur.append(line.strip())
    pkgs = []
    for line in secs.get("list", []):
        if m := LINE_RE.match(line):
            name, suites, new, _arch, old = m.groups()
            pkgs.append({"name": name, "from": old, "to": new, "security": "-security" in suites})
    stamp = secs.get("stamp", [])
    reboot = secs.get("reboot", [])
    return {"packages": pkgs, "count": len(pkgs), "security": sum(p["security"] for p in pkgs),
            "checked_at": int(stamp[0]) if stamp and stamp[0].isdigit() else None,
            "reboot": bool(reboot), "reboot_pkgs": reboot[1:]}


def run_script(upgrade: bool) -> str:
    """Arranca apt en el host, suelto del panel. Escribe «busy» si ya hay uno en marcha."""
    steps = 'echo "$ sudo apt update"; sudo -n apt update'
    if upgrade:
        steps += ' && { echo; echo "$ sudo apt upgrade -y"; sudo -n apt upgrade -y; }'
    inner = f'{steps}; echo "@rc $?"'
    return (f'mkdir -p "{DIR}"; if {RUNNING}; then echo busy; exit 0; fi\n'
            f"setsid nohup sh -c '{inner}' </dev/null >\"{LOG}\" 2>&1 & echo $! >\"{PID}\"; echo started\n")


def parse_job(out: str) -> dict | None:
    """El registro → {status, lines} como las demás tareas (watchJob). None si nunca se ha actualizado."""
    if out.startswith("@none"):
        return None
    running, _, log = out.partition("\n")
    lines = log.rstrip("\n").splitlines()
    rc = lines[-1][4:].strip() if lines and lines[-1].startswith("@rc ") else None
    if rc is not None:
        lines = lines[:-1]
    if rc == "0":
        status = "ok"
    elif rc is None and running == "@running":
        status = "running"
    else:
        status = "failed"
        if any("password is required" in x or "se requiere una contraseña" in x for x in lines):
            lines.append("")
            lines.append("sudo pide contraseña: añade en sudoers (sudo visudo -f /etc/sudoers.d/pocketpanel)")
            lines.append("  TU_USUARIO ALL=(root) NOPASSWD: /usr/bin/apt update, /usr/bin/apt upgrade -y")
        elif rc is None:
            lines.append("(se cortó antes de terminar)")
    return {"status": status, "lines": lines[-300:]}


class Packages:
    def __init__(self, ssh):
        self.ssh = ssh
        self._list, self._at = None, 0.0

    async def listing(self, fresh: bool = False) -> dict:
        if fresh or not self._list or time.monotonic() - self._at > FRESH:
            self._list, self._at = parse_list(await self.ssh.run(LIST_SCRIPT, timeout=30)), time.monotonic()
        return {**self._list, "running": await self.running()}

    async def running(self) -> bool:
        return (await self.ssh.run(f"{RUNNING} && echo yes; true")).strip() == "yes"

    async def start(self, upgrade: bool) -> None:
        out = await self.ssh.run(run_script(upgrade))
        if "busy" in out:
            raise PackagesError("ya hay una actualización en marcha")
        if "started" not in out:
            raise PackagesError("no se pudo arrancar apt")
        self._list = None

    async def job(self) -> dict | None:
        out = await self.ssh.run(f'[ -e "{LOG}" ] || {{ echo @none; exit 0; }}; '
                                 f'if {RUNNING}; then echo @running; else echo @done; fi; tail -n 400 "{LOG}"')
        return parse_job(out)
