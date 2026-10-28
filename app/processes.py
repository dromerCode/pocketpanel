"""Los procesos del host, como un top ligero: CPU (entre dos muestras, como top y btop) y memoria de cada uno.

Solo se lee cuando alguien tiene abierta la lista de Estado. Una muestra es leer /proc de una vez (un `cat`) más un
`ps` para el usuario y la línea de órdenes; el % de CPU sale de la diferencia con la muestra anterior. Si no hay
una reciente (la primera vez que se abre), el script toma dos con un segundo de separación. Con varias pantallas
abiertas, una muestra de hace menos de 4 s sirve para todas (cada una con su orden y su filtro).

El cgroup de cada proceso dice si es de un contenedor de Docker, y cuál."""
import asyncio
import re
import time

PROCS_SCRIPT = r"""
echo @stat; head -1 /proc/stat
echo @n; nproc
echo @mem; grep '^MemTotal:' /proc/meminfo
echo @page; getconf PAGESIZE
echo @procs; cat /proc/[0-9]*/stat 2>/dev/null
echo @ps; COLUMNS=300 ps -eo pid=,user:32=,args= 2>/dev/null
echo @cg; grep -oE 'docker[-/][0-9a-f]{64}' /proc/[0-9]*/cgroup 2>/dev/null
true
"""
WARM = "echo @stat0; head -1 /proc/stat; echo @procs0; cat /proc/[0-9]*/stat 2>/dev/null; sleep 1\n"
STALE = 30  # s: una muestra más vieja no sirve para el % de CPU
FRESH = 4
LIMIT = 40
SORTS = ("cpu", "mem")
SIGNALS = ("TERM", "KILL")
CG_RE = re.compile(r"^/proc/(\d+)/cgroup:docker[-/]([0-9a-f]{64})$")


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


def parse_procs(out: str, prev: tuple | None):
    """→ (muestra, la base para la próxima). Sin muestra anterior la CPU sale como None."""
    s = _sections(out)
    total = _total(s.get("stat", []))
    procs = parse_stat(s.get("procs", []))
    if "stat0" in s:
        prev = (_total(s["stat0"]), {k: v["ticks"] for k, v in parse_stat(s["procs0"]).items()})
    ncpu = int(s["n"][0]) if s.get("n", [""])[0].strip().isdigit() else 1
    page = int(s["page"][0]) if s.get("page", [""])[0].strip().isdigit() else 4096
    mem_total = int(s["mem"][0].split()[1]) * 1024 if s.get("mem") else 0
    ps = parse_ps(s.get("ps", []))
    cg = {int(m[1]): m[2] for line in s.get("cg", []) if (m := CG_RE.match(line.strip()))}
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
                     "state": p["state"], "cpu": cpu, "mem": rss, "container": cg.get(p["pid"]),
                     "mem_pct": round(rss * 100 / mem_total, 1) if mem_total else None})
    snap = {"rows": rows, "ncpu": ncpu, "mem_total": mem_total}
    return snap, (total, {k: v["ticks"] for k, v in procs.items()})


def select(snap: dict, sort: str = "cpu", q: str = "", limit: int = LIMIT) -> dict:
    """Lo que se enseña de una muestra: ordenado por CPU o memoria y filtrado por `q` (pid, usuario, orden o
    contenedor, sin distinguir mayúsculas)."""
    rows = snap["rows"]
    q = q.strip().casefold()
    if q:
        rows = [r for r in rows if q == str(r["pid"]) or q in r["user"].casefold() or q in r["cmd"].casefold()
                or q in (r.get("container") or "").casefold()]
    key = (lambda r: (r["cpu"] or 0, r["mem"])) if sort == "cpu" else (lambda r: (r["mem"], r["cpu"] or 0))
    rows = sorted(rows, key=key, reverse=True)
    return {"count": len(snap["rows"]), "shown": len(rows), "ncpu": snap["ncpu"], "mem_total": snap["mem_total"],
            "sort": sort, "procs": rows[:limit]}


class ProcessError(Exception):
    pass


class Processes:
    def __init__(self, ssh, docker=None):
        self.ssh, self.docker = ssh, docker
        self._prev = None
        self._snap, self._at = None, 0.0
        self._lock = asyncio.Lock()

    async def _names(self) -> dict:
        """id del contenedor → nombre."""
        if not self.docker:
            return {}
        try:
            return {c["Id"]: c["Names"][0].lstrip("/") for c in await self.docker.containers()}
        except Exception:  # noqa: BLE001 — sin Docker la lista sale igual, sin contenedores
            return {}

    async def sample(self, sort: str = "cpu", q: str = "") -> dict:
        sort = sort if sort in SORTS else "cpu"
        async with self._lock:  # dos pestañas a la vez no se pisan la muestra
            now = time.monotonic()
            if not self._snap or now - self._at >= FRESH:
                fresh = self._prev and now - self._at < STALE
                out, names = await asyncio.gather(self.ssh.run(PROCS_SCRIPT if fresh else WARM + PROCS_SCRIPT),
                                                  self._names())
                snap, self._prev = parse_procs(out, self._prev if fresh else None)
                for r in snap["rows"]:
                    if r["container"]:
                        r["container"] = names.get(r["container"], r["container"][:12])
                self._snap, self._at = snap, time.monotonic()
            return select(self._snap, sort, q[:100])

    async def signal(self, pid, sig: str) -> None:
        """kill -TERM (o -KILL) como el usuario del host: solo llega a sus procesos, no a los de root."""
        if not isinstance(pid, int) or pid <= 1 or sig not in SIGNALS:
            raise ProcessError("proceso o señal no válidos")
        out = await self.ssh.run(f"kill -s {sig} -- {pid} 2>&1; echo \"@rc $?\"")
        rc = out.rstrip().rsplit("@rc ", 1)[-1]
        if rc != "0":
            msg = out.rsplit("@rc", 1)[0].strip().splitlines()
            err = msg[-1] if msg else "no se pudo"
            if "not permitted" in err or "no permitido" in err:
                err = "no es tuyo (el panel no usa sudo)"
            elif "No such process" in err or "No existe" in err:
                err = "ese proceso ya no existe"
            raise ProcessError(err)
        self._snap = None  # que la próxima lista ya no lo traiga
