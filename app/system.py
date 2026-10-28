import asyncio
import fnmatch
import time

# Sensores de CPU conocidos, por preferencia; si no hay ninguno se usa el primero que aparezca.
SENSORS = ("k10temp", "zenpower", "coretemp", "cpu_thermal", "acpitz")
SKIP_MOUNTS = ("/boot", "/snap/", "/var/lib/docker")

# Se ejecuta en el host por SSH; timeout en df por los montajes de red (SMB, rclone).
SYSTEM_SCRIPT = r"""
echo @stat; head -1 /proc/stat
echo @mem; grep -E '^(MemTotal|MemAvailable):' /proc/meminfo
echo @up; cat /proc/uptime
echo @load; cat /proc/loadavg
echo @temp; for h in /sys/class/hwmon/hwmon*; do [ -r $h/temp1_input ] && echo "$(cat $h/name) $(cat $h/temp1_input)"; done 2>/dev/null
true
"""
DF_SCRIPT = "echo @df; timeout 4 df -P -B1 2>/dev/null\n"
FRESH = 4      # s: una muestra así de reciente sirve a todos (el móvil y el PC a la vez, el monitor…)
DF_EVERY = 30  # s: el espacio libre cambia despacio y df es lo más lento (montajes de red)


def _sections(out: str) -> dict:
    secs, cur = {}, None
    for line in out.splitlines():
        if line.startswith("@"):
            cur = line[1:].strip()
            secs[cur] = []
        elif cur and line.strip():
            secs[cur].append(line)
    return secs


def disk_label(mount: str) -> str:
    return mount.rstrip("/").rsplit("/", 1)[-1] or "/"


def _wanted(dev: str, mount: str, globs: list) -> bool:
    if globs:
        return any(fnmatch.fnmatchcase(mount, g) for g in globs)
    return dev.startswith("/dev/") and not mount.startswith(SKIP_MOUNTS)


def _temp(lines: list) -> float | None:
    found = {}
    for l in lines:
        p = l.split()
        if len(p) == 2 and p[1].lstrip("-").isdigit():
            found.setdefault(p[0], int(p[1]))
    if not found:
        return None
    v = next((found[s] for s in SENSORS if s in found), next(iter(found.values())))
    return int(v / 100) / 10


def _disks(lines: list, globs: list) -> list:
    disks = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        mount = " ".join(parts[5:])
        if not _wanted(parts[0], mount, globs):
            continue
        try:
            size, used, avail = int(parts[1]), int(parts[2]), int(parts[3])
        except ValueError:
            continue
        pct = round(used * 100 / size) if size else 0
        disks.append({"mount": mount, "size": size, "used": used, "avail": avail, "pct": pct})
    return disks


def parse_system(out: str, prev_cpu: tuple | None, disks: list | None = None):
    s = _sections(out)
    r = {"cpu": None, "mem": None, "uptime": None, "load": None, "temp": None, "disks": []}
    cpu = prev_cpu
    try:
        vals = [int(x) for x in s["stat"][0].split()[1:]]
        total, idle = sum(vals), vals[3] + (vals[4] if len(vals) > 4 else 0)
        cpu = (total, idle)
        if prev_cpu and total > prev_cpu[0]:
            dt, di = total - prev_cpu[0], idle - prev_cpu[1]
            r["cpu"] = round((dt - di) * 100 / dt, 1)
    except (KeyError, IndexError, ValueError):
        pass
    try:
        m = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in s["mem"]}
        r["mem"] = {"total": m["MemTotal"], "used": m["MemTotal"] - m["MemAvailable"]}
    except (KeyError, IndexError, ValueError):
        pass
    try:
        r["uptime"] = int(float(s["up"][0].split()[0]))
    except (KeyError, IndexError, ValueError):
        pass
    try:
        r["load"] = [float(x) for x in s["load"][0].split()[:3]]
    except (KeyError, IndexError, ValueError):
        pass
    r["temp"] = _temp(s.get("temp", []))
    r["disks"] = _disks(s.get("df", []), disks or [])
    return r, cpu


class SystemSampler:
    """Una sola medición del host para todos los que la piden: la API de Estado (cada 5 s por pantalla abierta) y el
    monitor (cada 30 s). Si la última tiene menos de `max_age` segundos se reutiliza; df solo cada 30 s."""

    def __init__(self, ssh, docker, disks: list | None = None):
        self.ssh, self.docker, self.disks = ssh, docker, disks
        self._lock = asyncio.Lock()
        self._cpu_prev = None
        self._last, self._at = None, 0.0
        self._disks, self._df_at = [], -DF_EVERY

    async def sample(self, max_age: float = FRESH) -> tuple[dict, list]:
        """→ (lo de /api/system sin contenedores, la lista de contenedores de Docker)."""
        async with self._lock:
            now = time.monotonic()
            if self._last and now - self._at < max_age:
                return self._last
            df = now - self._df_at >= DF_EVERY
            out, containers = await asyncio.gather(self.ssh.run(SYSTEM_SCRIPT + (DF_SCRIPT if df else "")),
                                                   self.docker.containers())
            r, self._cpu_prev = parse_system(out, self._cpu_prev, self.disks)
            if df:
                self._disks, self._df_at = r["disks"], now
            r["disks"] = self._disks
            self._last, self._at = (r, containers), now
            return self._last
