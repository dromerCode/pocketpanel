import asyncio
import json
import logging
import re
import shlex
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("pocketpanel.backup")

ROOT_DIR = "/etc/pocketpanel"
SCRIPTS = Path(__file__).parent / "scripts"
LABEL_RE = re.compile(r"^[a-z0-9-]{0,40}$")
DEST_RE = re.compile(r"^([^:\s]+):(/\S*)$")


def snapshot_name(date: str, label: str = "") -> str:
    if not LABEL_RE.match(label):
        raise ValueError("etiqueta no válida")
    return f"{date}-{label}" if label else date


def script(name: str) -> str:
    return (SCRIPTS / name).read_text()


def backup_env(opts: dict) -> dict:
    """Variables que esperan backup.sh y restore.sh, sacadas de modules.backups de config.yml."""
    m = DEST_RE.match(opts["dest"])
    if not m:
        raise ValueError("backups.dest tiene que ser usuario@host:/ruta/absoluta")
    ssh = [opts["ssh_options"]] if opts.get("ssh_options") else []  # las del usuario mandan (van primero)
    ssh.append("-o BatchMode=yes -o ConnectTimeout=10")
    if opts.get("ssh_key"):
        ssh.append(f"-i {shlex.quote(opts['ssh_key'])}")
    return {"SRC": opts["source"].rstrip("/") + "/", "DEST_HOST": m.group(1), "DEST_PATH": m.group(2),
            "SSH_OPTS": " ".join(ssh), "KEEP_DAYS": str(opts.get("keep_days", 7)),
            "EXCLUDES": "\n".join(opts.get("excludes") or [])}


def host_script(name: str, args: list[str], opts: dict) -> str:
    """Con la parte de root instalada (sudoers) se usa la copia de /etc/pocketpanel; si no, el script del panel
    como el usuario del host."""
    a = " ".join(shlex.quote(x) for x in args)
    env = " ".join(f"{k}={shlex.quote(v)}" for k, v in backup_env(opts).items())
    # sudo -l: ¿puedo ejecutarlo como root sin contraseña? (/etc/sudoers.d no siempre se puede leer)
    return (f"if [ -x {ROOT_DIR}/{name} ] && sudo -n -l {ROOT_DIR}/{name} >/dev/null 2>&1; then\n"
            f"  sudo -n {ROOT_DIR}/{name} {a} 2>&1\n"
            f"else\n  {env} bash -c {shlex.quote(script(name))} {name} {a} 2>&1 </dev/null\nfi\n")


def run_command(snap: str, opts: dict) -> str:
    return host_script("backup.sh", [snap], opts)


def parse_result(out: str) -> dict:
    m = re.search(r"PP_OK (\d+) (\d+) (\d+)", out)
    if m:
        d = re.search(r"PP_DENIED (\d+)", out)
        dirs = [l.split(None, 2)[2] for l in out.splitlines() if l.startswith("PP_DIR ")]
        changed = [l[len("PP_CHANGED "):] for l in out.splitlines() if l.startswith("PP_CHANGED ")]
        return {"ok": True, "total": int(m.group(1)), "size": int(m.group(2)), "count": int(m.group(3)),
                "denied": int(d.group(1)) if d else 0, "denied_dirs": dirs, "root": "PP_MODE root" in out,
                "changed": changed}
    f = re.search(r"PP_FAIL (.*)", out)
    tail = "\n".join(l for l in out.strip().splitlines()[-5:])
    return {"ok": False, "error": f.group(1).strip() if f else (tail or "sin salida")}


class Backup:
    def __init__(self, ssh, opts: dict, data_dir: str, tz, push=None):
        self.ssh, self.opts, self.tz, self.push = ssh, opts, tz, push
        self.file = Path(data_dir) / "backup.json"
        self.running = False
        self._lock = asyncio.Lock()

    def state(self) -> dict:
        try:
            s = json.loads(self.file.read_text())
        except (OSError, ValueError):
            s = {}
        return {**s, "running": self.running}

    def _save(self, s: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(s))

    async def run(self, label: str = "") -> dict:
        snap = snapshot_name(datetime.now(self.tz).strftime("%Y-%m-%d"), label)
        async with self._lock:
            if not label and self.state().get("daily") == snap:
                return self.state().get("last") or {"ok": True, "snapshot": snap}
            self.running = True
            t0 = time.time()
            try:
                proc = await self.ssh.process(run_command(snap, self.opts))
                out = await proc.stdout.read()
                await proc.wait(check=False)
                res = parse_result(out)
            except Exception as e:  # noqa: BLE001
                res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            finally:
                self.running = False
            res.update(snapshot=snap, at=int(time.time()), seconds=int(time.time() - t0))
            s = self.state()
            s.pop("running", None)
            s["last"] = res
            if res["ok"]:
                s["last_ok"] = res
            if not label:  # el diario cuenta como hecho aunque falle (se avisa; no reintentar cada 30 s)
                s["daily"] = snap
            self._save(s)
            log.info("backup %s: %s", snap, res)
            if not res["ok"] and self.push:
                await self.push.send("Backup fallido", res["error"][:200], "/#status")
            return res
