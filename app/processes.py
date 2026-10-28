"""Los procesos del host, como un top ligero: CPU (entre dos muestras, como top y btop) y memoria de cada uno.

Solo se lee cuando alguien tiene abierta la lista de Estado. Una muestra es leer /proc de una vez (un `cat`) más un
`ps` para el usuario y la línea de órdenes; el % de CPU sale de la diferencia con la muestra anterior. Si no hay
una reciente (la primera vez que se abre), el script toma dos con un segundo de separación."""
import asyncio
import time

PROCS_SCRIPT = r"""
echo @stat; head -1 /proc/stat
echo @n; nproc
echo @mem; grep '^MemTotal:' /proc/meminfo
echo @page; getconf PAGESIZE
echo @procs; cat /proc/[0-9]*/stat 2>/dev/null
echo @ps; COLUMNS=300 ps -eo pid=,user:32=,args= 2>/dev/null
true
"""
WARM = "echo @stat0; head -1 /proc/stat; echo @procs0; cat /proc/[0-9]*/stat 2>/dev/null; sleep 1\n"
STALE = 30  # s: una muestra más vieja no sirve para el % de CPU
LIMIT = 40
SORTS = ("cpu", "mem")


def _sections(out: str) -> dict:
    secs, cur = {}, None
    for line in out.splitlines():
        if line.startswith("@") and line[1:].strip().isalnum():
            cur = line[1:].strip()
            secs[cur] = []
        elif cur and line.strip():
            secs[cur].append(line)
    return secs


def _total(lines: list) -> int:
    return sum(int(x) for x in lines[0].split()[1:9]) if lines else 0


def parse_stat(lines: list) -> dict:
    """/proc/<pid>/stat → {(pid, inicio): {...}}; el inicio distingue un pid reutilizado. Sin los hilos del kernel."""
    out = {}
    for line in lines:
        try:
            pid_s, rest = line.split(" (", 1)
            name, rest = rest.rsplit(") ", 1)
            f = rest.split()
            pid, ppid = int(pid_s), int(f[1])
            if pid == 2 or ppid == 2:
                continue
            out[(pid, int(f[19]))] = {"pid": pid, "name": name, "state": f[0], "ticks": int(f[11]) + int(f[12]),
                                      "rss": int(f[21])}
        except (ValueError, IndexError):
            continue
    return out


def parse_ps(lines: list) -> dict:
    out = {}
    for line in lines:
        p = line.split(None, 2)
        if len(p) >= 2 and p[0].isdigit():
            out[int(p[0])] = (p[1], p[2] if len(p) > 2 else "")
    return out


def parse_procs(out: str, prev: tuple | None, sort: str = "cpu", limit: int = LIMIT, q: str = ""):
    """→ (respuesta, muestra para la próxima vez). Sin muestra anterior la CPU sale como None. `q` filtra por pid,
    usuario u orden (sin distinguir mayúsculas)."""
    s = _sections(out)
    total = _total(s.get("stat", []))
    procs = parse_stat(s.get("procs", []))
    if "stat0" in s:
        prev = (_total(s["stat0"]), {k: v["ticks"] for k, v in parse_stat(s["procs0"]).items()})
    ncpu = int(s["n"][0]) if s.get("n", [""])[0].strip().isdigit() else 1
    page = int(s["page"][0]) if s.get("page", [""])[0].strip().isdigit() else 4096
    mem_total = int(s["mem"][0].split()[1]) * 1024 if s.get("mem") else 0
    ps = parse_ps(s.get("ps", []))
    span = total - prev[0] if prev else 0
    rows = []
    for key, p in procs.items():
        cpu = None
        if prev and span > 0:
            # Como top: 100 % es un núcleo entero (un proceso con 4 hilos a tope en 4 núcleos marca 400 %)
            # (uno que no estaba ha nacido después: todo lo suyo es de este intervalo)
            cpu = round(max(0, p["ticks"] - prev[1].get(key, 0)) * 100 * ncpu / span, 1)
        user, cmd = ps.get(p["pid"], ("", ""))
        rss = p["rss"] * page
        rows.append({"pid": p["pid"], "name": p["name"], "user": user, "cmd": cmd or f"[{p['name']}]",
                     "state": p["state"], "cpu": cpu, "mem": rss,
                     "mem_pct": round(rss * 100 / mem_total, 1) if mem_total else None})
    count = len(rows)
    q = q.strip().casefold()
    if q:
        rows = [r for r in rows if q == str(r["pid"]) or q in r["user"].casefold() or q in r["cmd"].casefold()]
    key = (lambda r: (r["cpu"] or 0, r["mem"])) if sort == "cpu" else (lambda r: (r["mem"], r["cpu"] or 0))
    rows.sort(key=key, reverse=True)
    resp = {"count": count, "shown": len(rows), "ncpu": ncpu, "mem_total": mem_total, "sort": sort,
            "procs": rows[:limit]}
    return resp, (total, {k: v["ticks"] for k, v in procs.items()})


class Processes:
    def __init__(self, ssh):
        self.ssh = ssh
        self._prev = None
        self._at = 0.0
        self._lock = asyncio.Lock()

    async def sample(self, sort: str = "cpu", q: str = "") -> dict:
        sort = sort if sort in SORTS else "cpu"
        async with self._lock:  # dos pestañas a la vez no se pisan la muestra
            fresh = self._prev and time.monotonic() - self._at < STALE
            out = await self.ssh.run(PROCS_SCRIPT if fresh else WARM + PROCS_SCRIPT)
            r, self._prev = parse_procs(out, self._prev if fresh else None, sort, q=q[:100])
            self._at = time.monotonic()
            return r
