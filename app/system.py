import fnmatch

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
echo @df; timeout 4 df -P -B1 2>/dev/null
true
"""


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
