"""Salud de los discos (SMART), para la lucecita de cada disco en Estado, sus avisos y sus exámenes.

Se lee con `sudo -n smartctl -j` (sin sudo, smartctl no puede leer los discos) cada 10 minutos, y nunca despierta
un disco dormido (`-n standby`: si está parado se queda con lo último que se supo). Cada disco sale con un nivel:
  bad   el SMART dice que falla, hay sectores pendientes o incorregibles, o el último examen falló
  warn  hay sectores reasignados (el disco ya ha cambiado alguno por uno de reserva) o pasa de la temperatura
  ok    nada de eso
  unknown  no se puede leer (sin permiso, un adaptador USB que no deja…)

Los avisos son por cambios: un contador que sube (sectores, errores de cable), un nivel que empeora, un examen que
falla. Lo último visto se guarda en data/ para que un reinicio del panel no repita avisos.

Los exámenes (self-tests) los hace el propio disco por dentro, sin parar nada: el corto tarda un par de minutos y el
largo, horas (lee el disco entero). Se pueden pedir a mano o programar."""
import asyncio
import json
import logging
import os
import re
import shlex
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("pocketpanel.smart")

FILE = "disk_health.json"
EVERY = 600  # s entre lecturas
DEFAULTS = {"notify": True, "temp_limit": 55, "short": "weekly", "long": "monthly", "at": "03:00"}
SCHEDULES = {"short": ("off", "daily", "weekly"), "long": ("off", "weekly", "monthly")}
TESTS = ("short", "long")
DEV_RE = re.compile(r"^/dev/(sd[a-z]+|hd[a-z]+|vd[a-z]+|nvme\d+n\d+)$")

SCRIPT = r"""
echo @map; lsblk -rnpbo NAME,TYPE,SIZE,PKNAME,MOUNTPOINT 2>/dev/null
sudo -n true 2>/dev/null && S="sudo -n " || S=""
echo "@sudo ${S:+yes}"
for d in $(lsblk -dnpbo NAME,TYPE,SIZE 2>/dev/null | awk '$2=="disk" && $3>0 {print $1}'); do
  echo "@disk $d"; ${S}smartctl -n standby -j -H -A -i -c -l selftest "$d" 2>/dev/null | tr -d '\n'; echo
done
true
"""

ATTR = {5: "realloc", 197: "pending", 198: "uncorrectable", 199: "crc"}
COUNTERS = ("realloc", "pending", "uncorrectable", "crc", "media_errors")


def _attrs(j: dict) -> dict:
    out = {}
    for a in (j.get("ata_smart_attributes") or {}).get("table") or []:
        if a.get("id") in ATTR:
            out[ATTR[a["id"]]] = (a.get("raw") or {}).get("value")
    return out


def parse_disk(dev: str, raw: str, temp_limit: int) -> dict:
    """Lo que dice smartctl de un disco → {dev, model, level, problems, …}."""
    d = {"dev": dev, "model": None, "serial": None, "level": "unknown", "problems": [], "asleep": False,
         "temp": None, "hours": None, "rotational": None, "test": None, "testing": None}
    try:
        j = json.loads(raw)
    except ValueError:
        d["problems"] = ["no se puede leer el SMART"]
        return d
    exit_status = (j.get("smartctl") or {}).get("exit_status", 0)
    if exit_status & 2 and "standby" in json.dumps((j.get("smartctl") or {}).get("messages") or []).lower():
        d["asleep"] = True
        return d
    d["model"], d["serial"] = j.get("model_name"), j.get("serial_number")
    d["rotational"] = (j.get("rotation_rate") or 0) > 0
    d["temp"] = (j.get("temperature") or {}).get("current")
    d["hours"] = (j.get("power_on_time") or {}).get("hours")
    d.update(_attrs(j))
    nv = j.get("nvme_smart_health_information_log") or {}
    if nv:
        d["media_errors"] = nv.get("media_errors")
        d["wear"] = nv.get("percentage_used")
    status = j.get("smart_status")
    if status is None and not d["model"]:
        d["problems"] = ["no da datos SMART (¿adaptador USB?)" if exit_status & 2 else "sin permiso para leer el SMART"]
        return d

    # El examen: el último que terminó y si hay uno en marcha
    st = ((j.get("ata_smart_data") or {}).get("self_test") or {}).get("status") or {}
    if 241 <= (st.get("value") or 0) <= 249:
        d["testing"] = st.get("remaining_percent", (st["value"] - 240) * 10)
    tab = ((j.get("ata_smart_self_test_log") or {}).get("standard") or {}).get("table") or []
    tab = tab or ((j.get("nvme_self_test_log") or {}).get("table") or [])
    if tab:
        t = tab[0]
        res = t.get("status") or t.get("self_test_result") or {}
        d["test"] = {"type": (t.get("type") or t.get("self_test_code") or {}).get("string", ""),
                     # passed: None si no lo dice (p. ej. un examen en marcha), y eso no es un fallo
                     "passed": res.get("passed"), "result": res.get("string", ""),
                     "hours": t.get("lifetime_hours", t.get("power_on_hours"))}

    bad, warn = [], []
    if status and status.get("passed") is False:
        bad.append("el propio disco dice que está fallando (SMART)")
    if d.get("pending"):
        bad.append(f"{d['pending']} sectores pendientes: no se pueden leer bien")
    if d.get("uncorrectable"):
        bad.append(f"{d['uncorrectable']} sectores incorregibles")
    if d.get("media_errors"):
        bad.append(f"{d['media_errors']} errores de lectura")
    if (nv.get("critical_warning") or 0) > 0:
        bad.append("el disco NVMe avisa de un problema grave")
    if d["test"] and d["test"]["passed"] is False:
        bad.append(f"el último examen falló ({d['test']['result']})")
    if d.get("realloc"):
        warn.append(f"{d['realloc']} {'sector reasignado' if d['realloc'] == 1 else 'sectores reasignados'}: "
                    "el disco ya ha cambiado alguno por uno de reserva; que no siga subiendo")
    if (d.get("wear") or 0) >= 90:
        warn.append(f"desgastado al {d['wear']}%")
    if d["temp"] is not None and d["temp"] >= temp_limit:
        warn.append(f"a {d['temp']}° (tu límite es {temp_limit}°)")
    d["problems"] = bad + warn
    d["level"] = "bad" if bad else "warn" if warn else "ok"
    return d


def parse_health(out: str, temp_limit: int) -> dict:
    """{"sudo": bool, "disks": [...], "mounts": {punto de montaje: disco}}"""
    mounts, disks, sudo = {}, [], False
    sec = None
    for line in out.splitlines():
        if line.startswith("@map"):
            sec = "map"
        elif line.startswith("@sudo"):
            sudo, sec = line.strip().endswith("yes"), None
        elif line.startswith("@disk "):
            sec = ("disk", line[6:].strip())
        elif sec == "map" and line.strip():
            p = line.split(" ")
            # NAME TYPE SIZE PKNAME MOUNTPOINT: el disco de una partición es su PKNAME; un disco sin particiones, él
            if len(p) >= 5 and p[4] and p[1] != "loop":
                mounts[p[4].replace("\\x20", " ")] = p[3] or p[0]
        elif isinstance(sec, tuple) and line.strip():
            disks.append(parse_disk(sec[1], line, temp_limit))
            sec = None
    return {"sudo": sudo, "disks": disks, "mounts": mounts}


def due(sched: str, now: datetime, at: str, last: str | None) -> bool:
    """¿Toca hoy un examen con el horario `sched`? `last` es el día (AAAA-MM-DD) del último."""
    if sched == "off" or now.strftime("%H:%M") < at or last == now.strftime("%Y-%m-%d"):
        return False
    return sched == "daily" or (sched == "weekly" and now.weekday() == 6) or (sched == "monthly" and now.day == 1)


class SmartError(Exception):
    pass


class DiskHealth:
    def __init__(self, ssh, data_dir: str, tz=None):
        self.ssh, self.path, self.tz = ssh, Path(data_dir) / FILE, tz
        self._state = self._load()
        self._health, self._at = None, 0.0
        self._lock = asyncio.Lock()

    # --- ajustes y lo último visto (data/disk_health.json) ----------------------------------------------------
    def _load(self) -> dict:
        try:
            s = json.loads(self.path.read_text())
        except (OSError, ValueError):
            s = {}
        return {"settings": {**DEFAULTS, **(s.get("settings") or {})}, "seen": s.get("seen") or {},
                "last_test": s.get("last_test") or {}, "known": s.get("known") or {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state))
        os.replace(tmp, self.path)

    @property
    def settings(self) -> dict:
        return dict(self._state["settings"])

    def set_settings(self, b: dict) -> dict:
        s = dict(self._state["settings"])
        if "notify" in b:
            s["notify"] = bool(b["notify"])
        if "temp_limit" in b:
            t = b["temp_limit"]
            if not isinstance(t, int) or isinstance(t, bool) or not 30 <= t <= 90:
                raise SmartError("la temperatura límite tiene que ser de 30 a 90 °C")
            s["temp_limit"] = t
        for k in TESTS:
            if k in b:
                if b[k] not in SCHEDULES[k]:
                    raise SmartError(f"examen {k}: tiene que ser {', '.join(SCHEDULES[k])}")
                s[k] = b[k]
        if "at" in b:
            if not isinstance(b["at"], str) or not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", b["at"]):
                raise SmartError("la hora tiene que ser HH:MM")
            s["at"] = b["at"]
        self._state["settings"] = s
        self._save()
        self._health = None  # el límite de temperatura cambia los niveles
        return s

    # --- lectura ------------------------------------------------------------------------------------------------
    async def health(self, max_age: float = EVERY) -> dict:
        async with self._lock:
            if self._health is None or time.monotonic() - self._at > max_age:
                h = parse_health(await self.ssh.run(SCRIPT, timeout=90), self._state["settings"]["temp_limit"])
                # un disco dormido: lo último que se supo de él, marcado como dormido
                old = {d["dev"]: d for d in (self._health or {}).get("disks", [])}
                h["disks"] = [{**old[d["dev"]], "asleep": True} if d["asleep"] and d["dev"] in old else d
                              for d in h["disks"]]
                self._health, self._at = h, time.monotonic()
            return self._health

    # --- avisos -------------------------------------------------------------------------------------------------
    def changes(self, h: dict) -> list[str]:
        """Lo que ha empeorado desde lo último visto (y lo guarda)."""
        out, seen, known = [], self._state["seen"], self._state["known"]
        for d in h["disks"]:
            if d["level"] == "unknown" or d["asleep"] or not d.get("serial"):
                continue
            name = d["dev"].rsplit("/", 1)[-1]
            prev = seen.get(d["serial"])
            now = {k: d.get(k) or 0 for k in COUNTERS}
            now["level"] = d["level"]
            now["test_failed"] = bool(d["test"] and d["test"]["passed"] is False)
            now["hot"] = d["temp"] is not None and d["temp"] >= self._state["settings"]["temp_limit"]
            known[d["serial"]] = name
            if prev:
                for k, label in (("pending", "sectores pendientes"), ("uncorrectable", "sectores incorregibles"),
                                 ("realloc", "sectores reasignados"), ("media_errors", "errores de lectura"),
                                 ("crc", "errores de cable (¿cable SATA flojo o malo?)")):
                    if now[k] > prev.get(k, 0):
                        out.append(f"Disco {name}: {label} {prev.get(k, 0)} → {now[k]}")
                if now["test_failed"] and not prev.get("test_failed"):
                    out.append(f"Disco {name}: el examen SMART ha fallado")
                if now["hot"] and not prev.get("hot"):
                    out.append(f"Disco {name} a {d['temp']}°")
                if d["level"] == "bad" and prev.get("level") != "bad" and not any(m.startswith(f"Disco {name}:") for m in out):
                    out.append(f"Disco {name}: {d['problems'][0]}")
            seen[d["serial"]] = now
        self._save()
        return out if self._state["settings"]["notify"] else []

    # --- exámenes -----------------------------------------------------------------------------------------------
    async def start_test(self, dev: str, kind: str) -> None:
        if kind not in TESTS or not DEV_RE.match(dev or ""):
            raise SmartError("disco o examen no válido")
        mode = "short" if kind == "short" else "long"
        out = await self.ssh.run(f"sudo -n smartctl -t {mode} {shlex.quote(dev)} 2>&1; echo \"@rc $?\"", timeout=30)
        rc = out.rstrip().rsplit("@rc ", 1)[-1]
        if rc not in ("0",) and "Testing has begun" not in out:
            if "password is required" in out or "contraseña" in out:
                raise SmartError("sudo pide contraseña: hace falta poder usar smartctl con sudo sin contraseña")
            lines = [l for l in out.rsplit("@rc", 1)[0].splitlines() if l.strip()]
            raise SmartError(lines[-1] if lines else "no se pudo empezar el examen")
        self._health = None

    async def tick(self, n: int, now: float) -> list:
        """Desde el monitor (cada 30 s): leer cada 10 min, avisar y lanzar los exámenes programados."""
        if n % (EVERY // 30):
            return []
        h = await self.health(max_age=0)
        notes = [(m, "/#status") for m in self.changes(h)]
        s, last = self._state["settings"], self._state["last_test"]
        dt = datetime.fromtimestamp(now, self.tz)
        for kind in ("long", "short"):  # si tocan los dos el mismo día, el largo (que ya incluye lo del corto)
            if due(s[kind], dt, s["at"], last.get(kind)):
                last[kind] = last["short"] = dt.strftime("%Y-%m-%d")
                for d in h["disks"]:
                    if d["level"] != "unknown" and not d["testing"]:
                        try:
                            await self.start_test(d["dev"], kind)
                        except SmartError as e:
                            log.info("examen %s de %s: %s", kind, d["dev"], e)
                self._save()
                break
        return notes
