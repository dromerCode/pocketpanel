"""Los servicios de systemd del host, para la pestaña Servicios (debajo de los contenedores).

No salen todos (un Ubuntu trae decenas que son fontanería del sistema): solo
  - los que has puesto tú: los de /etc/systemd/system y los de usuario (~/.config/systemd/user)
  - los que están en marcha y no son del sistema base (tailscaled, code-server, docker, ssh…)
  - cualquiera que haya fallado
Arrancar, parar y reiniciar los del sistema va con `sudo -n systemctl`; los de usuario, con `systemctl --user`."""
import json
import re
import shlex

UNIT_RE = re.compile(r"^[A-Za-z0-9@_.:\\-]{1,200}\.service$")
VERBS = ("start", "stop", "restart")
# Fontanería del sistema base: no se enseña aunque esté en marcha (sí si falla)
PLUMBING = re.compile(
    r"^(systemd-|dbus|getty@|serial-getty@|user@|user-runtime-dir@|polkit|udisks2|upower|thermald|fwupd|snapd|"
    r"plymouth|apparmor|apport|blk-availability|console-setup|keyboard-setup|kmod-|lvm2|netplan|setvtrgb|finalrd|"
    r"grub-|kdump|sysstat|ubuntu-|ufw|rsyslog|unattended-upgrades|accounts-daemon|avahi|bluetooth|colord|cups|gdm|"
    r"ModemManager|NetworkManager|wpa_supplicant|rtkit|switcheroo|power-profiles|packagekit|kerneloops|whoopsie|"
    r"irqbalance|multipathd|e2scrub|fstrim|man-db|logrotate|motd-news|apt-daily|dpkg-db-backup|ua-|esm-|"
    r"open-vm|qemu-guest|cloud-|pollinate|secureboot|lxd-agent|containerd|smartmontools|at-spi|"
    r"gnome-|pipewire|wireplumber|xdg-|evolution|tracker-|gvfs|pulseaudio|snap\.)")

LIST_SCRIPT = r"""
echo @system; systemctl list-units --type=service --all -o json --no-pager 2>/dev/null; echo
echo @mine; find /etc/systemd/system -maxdepth 1 -type f -name '*.service' -printf '%f\n' 2>/dev/null
echo @user; systemctl --user list-units --type=service --all -o json --no-pager 2>/dev/null; echo
echo @usermine; find "$HOME/.config/systemd/user" -maxdepth 1 -type f -name '*.service' -printf '%f\n' 2>/dev/null
true
"""
SHOW = "Id,Description,ActiveState,SubState,UnitFileState,ActiveEnterTimestamp,InactiveEnterTimestamp,MainPID,MemoryCurrent,Result"


class SystemdError(Exception):
    pass


def _sections(out: str) -> dict:
    secs, cur = {}, None
    for line in out.splitlines():
        if line.startswith("@") and line[1:].strip().isalpha():
            cur = secs.setdefault(line[1:].strip(), [])
        elif cur is not None and line.strip():
            cur.append(line)
    return secs


def _json(lines: list) -> list:
    try:
        return json.loads("".join(lines) or "[]")
    except ValueError:
        return []


def pick(out: str) -> list[tuple[str, str]]:
    """De todo lo que hay, los que se enseñan: [(scope, unidad)]."""
    s = _sections(out)
    chosen = []
    for scope, units, mine in (("system", _json(s.get("system", [])), set(s.get("mine", []))),
                               ("user", _json(s.get("user", [])), set(s.get("usermine", [])))):
        loaded = {u.get("unit") for u in units if u.get("load") == "loaded"}
        for u in units:
            name = u.get("unit", "")
            if u.get("load") != "loaded" or not UNIT_RE.match(name):
                continue
            if u.get("active") == "failed" or (not PLUMBING.match(name) and (name in mine or u.get("sub") == "running")):
                chosen.append((scope, name))
        # los tuyos que no están cargados (parados y sin activar) también: son tuyos
        chosen += [(scope, n) for n in sorted(mine - loaded) if UNIT_RE.match(n) and not PLUMBING.match(n)]
    return list(dict.fromkeys(chosen))


def show_script(units: list[tuple[str, str]]) -> str:
    parts = []
    for scope in ("system", "user"):
        names = [shlex.quote(n) for sc, n in units if sc == scope]
        if names:
            flag = " --user" if scope == "user" else ""
            parts.append(f"echo @{scope}; systemctl{flag} show --timestamp=unix -p {SHOW} --no-pager {' '.join(names)} 2>/dev/null")
    return "\n".join(parts) + "\ntrue\n"


def parse_show(out: str) -> list[dict]:
    items, scope, cur = [], None, None
    for line in out.splitlines() + [""]:
        if line.startswith("@") and line[1:].strip() in ("system", "user"):
            scope = line[1:].strip()
            continue
        if not line.strip():
            if cur and cur.get("Id"):
                items.append(_item(scope, cur))
            cur = None
            continue
        k, _, v = line.partition("=")
        cur = cur or {}
        cur[k] = v
    return items


def _item(scope: str, p: dict) -> dict:
    unit = p["Id"]
    active, sub = p.get("ActiveState", ""), p.get("SubState", "")
    mem = p.get("MemoryCurrent", "")
    up = active == "active" or active == "reloading" or active == "activating"
    since = (p.get("ActiveEnterTimestamp") if up else p.get("InactiveEnterTimestamp") or "").lstrip("@")
    title = unit.removesuffix(".service")
    return {"kind": "unit", "scope": scope, "unit": unit, "name": f"{scope}:{unit}", "title": title,
            "desc": p.get("Description", ""), "up": up, "active": active, "sub": sub,
            "failed": active == "failed", "enabled": p.get("UnitFileState", ""), "since": int(since) if since.isdigit() else None,
            "pid": int(p["MainPID"]) if p.get("MainPID", "0").isdigit() and p["MainPID"] != "0" else None,
            "mem": int(mem) if mem.isdigit() else None, "result": p.get("Result", "")}


def check_unit(scope: str, unit: str) -> None:
    if scope not in ("system", "user") or not UNIT_RE.match(unit or ""):
        raise SystemdError("servicio no válido")


def action_command(scope: str, unit: str, verb: str) -> str:
    check_unit(scope, unit)
    if verb not in VERBS:
        raise SystemdError("acción no válida")
    cmd = f"systemctl --user {verb}" if scope == "user" else f"sudo -n systemctl {verb}"
    return f"{cmd} {shlex.quote(unit)} 2>&1; echo \"@rc $?\""


def logs_command(scope: str, unit: str, lines: int = 200) -> str:
    check_unit(scope, unit)
    which = f"--user-unit {shlex.quote(unit)}" if scope == "user" else f"-u {shlex.quote(unit)}"
    # Lo último que haya (aunque sea de otro arranque) y luego en directo. Va con pseudoterminal: sin ella,
    # `journalctl -f` no suelta nada por el SSH
    base = f"journalctl {which} -o short-iso --no-pager"
    return (f"export SYSTEMD_COLORS=0; {base} -n {int(lines)} 2>&1 || true; echo '── en directo ──'; "
            f"exec {base} -n 0 -f 2>&1")


class Systemd:
    def __init__(self, ssh):
        self.ssh = ssh

    async def units(self) -> list[dict]:
        chosen = pick(await self.ssh.run(LIST_SCRIPT, timeout=20))
        if not chosen:
            return []
        items = parse_show(await self.ssh.run(show_script(chosen), timeout=20))
        return sorted(items, key=lambda x: (not x["failed"], x["scope"] != "system", x["title"].lower()))

    async def action(self, scope: str, unit: str, verb: str) -> None:
        out = await self.ssh.run(action_command(scope, unit, verb), timeout=90)
        rc = out.rstrip().rsplit("@rc ", 1)[-1]
        if rc != "0":
            msg = [line for line in out.rsplit("@rc", 1)[0].splitlines() if line.strip()]
            err = msg[-1] if msg else "no se pudo"
            if "password is required" in err or "contraseña" in err:
                err = "sudo pide contraseña: hace falta poder usar systemctl con sudo sin contraseña"
            raise SystemdError(err)
