"""Las webs de clientes: una VM que las sirve y este servidor de relevo.

Todo lo hace un script del host (`panel.sh`, junto a los demás scripts de clientes): este módulo solo lo llama por
SSH, convierte lo que imprime en datos para la app y comprueba lo que se le pide antes de pasárselo.

El script imprime secciones «@@nombre» con líneas «a|b|c» (o el JSON tal cual de restic y Cloudflare). Las acciones
corren en el host sueltas del panel (siguen aunque el panel se reinicie), una cada vez, y escriben en un registro
que aquí solo se lee."""
import json
import re
import shlex
import time
from datetime import datetime

OK_HTTP = {"200", "301", "302"}
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PATH_RE = re.compile(r"^/[A-Za-z0-9/_.-]*$")
DOMAIN_RE = re.compile(r"^([a-z0-9-]+\.)+[a-z]{2,}$")
SNAP_RE = re.compile(r"^[0-9a-f]{8,64}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SCRIPT_RE = re.compile(r"^[A-Za-z0-9_./~-]+$")
EVENT_RE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (.*)$")

CRONS = {  # id → (lo que lo reconoce en el crontab, título, para qué sirve, qué pasa si se pausa)
    "vigilancia": ("vigilar-vm.sh", "Vigilancia de la VM",
                   "Comprueba que las webs responden en la VM. Si la VM no responde 3 veces seguidas, pasa los "
                   "clientes a casa.", "Sin ella no hay relevo automático: si la VM cae, las webs caen."),
    "noche": ("copia-vm.sh", "Copia y despliegue de cada noche",
              "Baja los datos de la VM, los guarda en el historial y después publica lo que haya nuevo en la rama "
              "main de cada proyecto.", "Sin ella no hay copias nuevas ni se publica nada."),
    "ddns": ("cf-ddns.sh", "IP de casa en el DNS",
             "Mantiene en Cloudflare la IP de casa (sus subdominios y, durante un relevo, los dominios de clientes).",
             "Si la IP de casa cambia, lo de casa deja de ser accesible desde fuera."),
}
CONFIRM = {"a-casa": "casa", "a-la-vm": "vm"}  # lo que hay que escribir para confirmar (quitar/restaurar: el nombre)


class ClientesError(Exception):
    pass


def sections(out: str) -> list[tuple[str, list[str]]]:
    """«@@a\\nx\\n@@b\\ny» → [("a", ["x"]), ("b", ["y"])]. Una sección puede repetirse (una por zona, p. ej.)."""
    secs: list[tuple[str, list[str]]] = []
    for line in out.splitlines():
        if line.startswith("@@"):
            secs.append((line[2:].strip(), []))
        elif secs and line.strip():
            secs[-1][1].append(line)
    return secs


def first(secs, name) -> list[str]:
    return next((lines for n, lines in secs if n == name), [])


def _int(x, default=0) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


def _float(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _ts(text: str) -> int | None:
    """«2026-11-11 02:00:19» en la hora del servidor → epoch."""
    try:
        return int(datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S").astimezone().timestamp())
    except ValueError:
        return None


def _containers(lines) -> dict:
    out = {}
    for line in lines:
        name, state, status = (line.split("|") + ["", ""])[:3]
        out[name] = {"state": state, "status": status}
    return out


def parse_estado(out: str) -> dict:
    secs = sections(out)
    mode, _, since = (first(secs, "modo") or ["desconocido|"])[0].partition("|")
    vig = {"fails": 0, "partial": False, "maintenance": None}
    now, vm_ip = int(time.time()), ""
    for line in first(secs, "vigilancia"):
        k, *v = line.split("|")
        if k == "fallos":
            vig["fails"] = _int(v[0])
        elif k == "parcial":
            vig["partial"] = v[0] == "si"
        elif k == "mantenimiento":
            vig["maintenance"] = {"by": v[0], "since": _int(v[1]) if len(v) > 1 else None}
        elif k == "ahora":
            now = _int(v[0], now)
        elif k == "ips":
            vm_ip = v[0]

    names = [n for n, _ in secs]
    vm = {"ok": "vm-sys" in names and "vm-error" not in names, "ip": vm_ip, "containers": _containers(first(secs, "vm-docker"))}
    sysl = first(secs, "vm-sys")
    if vm["ok"] and len(sysl) >= 6:
        mem = {k.strip(): _int((v.split() or ["0"])[0]) * 1024 for k, _, v in (x.partition(":") for x in sysl[3:5])}
        disk = sysl[5].split() + ["0", "0", "0"]
        vm.update(uptime=_int((sysl[0].split() or ["0"])[0]), load=[_float(x, 0.0) for x in sysl[1].split()[:3]],
                  cpus=_int(sysl[2], 1), mem_total=mem.get("MemTotal", 0),
                  mem_used=mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
                  disk_total=_int(disk[1]), disk_used=_int(disk[2]))
    http_vm = dict(x.split("|")[:2] for x in first(secs, "vm-http") if "|" in x)
    public = {x.split("|")[0]: x.split("|")[1:] for x in first(secs, "publico")}
    home = _containers(first(secs, "casa-docker"))

    projects = []
    for line in first(secs, "proyectos"):
        f = line.split("|", 11)
        if len(f) < 12:
            continue
        name = f[0]
        pub = public.get(name, [])
        p = {"name": name, "repo": f[1], "type": f[2], "port": _int(f[3]), "data": f[4] == "si", "path": f[5],
             "domains": f[6].split(), "deployed": f[7], "failed": f[8], "deployed_at": _int(f[9]) or None,
             "commit_at": _int(f[10]) or None, "commit_msg": f[11],
             "http_vm": http_vm.get(name), "http_public": pub[0] if pub else None,
             "time_public": round(_float(pub[1]), 2) if len(pub) > 1 and _float(pub[1]) is not None else None,
             "vm": vm["containers"].get(name), "home": home.get(name)}
        p["public_ok"] = p["http_public"] in OK_HTTP
        here = p["home"] if mode == "casa" else p["vm"]
        p["running"] = bool(here and here["state"] == "running")
        p["ok"] = p["public_ok"] and p["running"]
        projects.append(p)

    job_line = (first(secs, "trabajo") or ["idle||"])[0].split("|")
    job = {"running": job_line[0] == "running", "name": job_line[1] if len(job_line) > 1 else "",
           "failed": len(job_line) > 2 and job_line[2] not in ("", "0")}
    copia = (first(secs, "copia") or ["fecha|"])[0].partition("|")[2]
    backup_at = _ts(copia) if copia else None

    problems = []
    if mode == "desconocido":
        problems.append("No se sabe dónde están servidos: Cloudflare no responde")
    if mode == "casa":
        problems.append("Los clientes están servidos desde casa (relevo)")
    if not vm["ok"]:
        problems.append("No se puede entrar en la VM")
    for p in projects:
        if not p["ok"]:
            problems.append(f"{p['name']} no responde" + (f" (HTTP {p['http_public']})" if p["http_public"] else ""))
        if p["failed"]:
            problems.append(f"{p['name']}: el último commit ({p['failed']}) falló al desplegar")
    if backup_at is None or now - backup_at > 26 * 3600:
        problems.append("La última copia tiene más de un día")
    bad = (not vm["ok"] and mode != "casa") or any(not p["ok"] for p in projects) or mode == "desconocido"
    return {"mode": mode, "since": since or None, "vigil": vig, "vm": vm, "projects": projects, "job": job,
            "backup_at": backup_at, "now": now, "problems": problems,
            "level": "bad" if bad else "warn" if problems else "ok"}


def parse_dns(out: str) -> dict:
    secs = sections(out)
    mode = (first(secs, "modo") or ["vm"])[0]
    home_ip = (first(secs, "ip-casa") or [""])[0]
    vm_ip = (first(secs, "ip-vm") or [""])[0]
    want = {}  # nombre → (tipo, proyecto, ip esperada, proxied esperado)
    for name in first(secs, "casa"):
        want[name] = ("casa", None, home_ip, False)
    for line in first(secs, "clientes"):
        name, _, proj = line.partition("|")
        want[name] = ("cliente", proj, home_ip if mode == "casa" else vm_ip, True)

    found, zones, zone, flag, errors = {}, [], None, False, []
    for sec, lines in secs:
        if sec == "zona" and lines:
            zone = {"name": lines[0], "status": "", "ns": [], "others": 0}
            zones.append(zone)
        elif sec == "error" and lines:
            errors.append(lines[0])
        elif sec == "ns" and zone and lines:
            status, _, ns = lines[0].partition("|")
            zone.update(status=status, ns=ns.split())
        elif sec == "registros" and zone:
            try:
                recs = json.loads("\n".join(lines)).get("result") or []
            except ValueError:
                errors.append(zone["name"])
                continue
            for r in recs:
                if not isinstance(r, dict) or not {"type", "name", "content"} <= r.keys():
                    continue
                if r["type"] == "TXT" and r["name"].startswith("_failover."):
                    flag = r["content"].strip('"') == "on"
                elif r["name"] in want and r["type"] in ("A", "AAAA", "CNAME"):
                    found.setdefault(r["name"], []).append(r)
                else:
                    zone["others"] += 1

    records = []
    for name, (kind, proj, ip, proxied) in want.items():
        recs = found.get(name, [])
        base = {"name": name, "kind": kind, "project": proj, "expected": ip, "expected_proxied": proxied}
        if not recs:
            records.append({**base, "type": None, "content": None, "proxied": None, "ok": False, "why": "no existe"})
        for r in recs:
            why = None
            if r["type"] != "A" or r["content"] != ip:
                why = f"debería apuntar a {ip or '?'}"
            elif bool(r.get("proxied")) != proxied:
                why = "debería ir por Cloudflare (nube naranja)" if proxied else "debería ir directo (nube gris)"
            records.append({**base, "type": r["type"], "content": r["content"], "proxied": bool(r.get("proxied")),
                            "ok": why is None, "why": why})
    return {"mode": mode, "home_ip": home_ip, "vm_ip": vm_ip, "flag": flag, "records": records, "zones": zones,
            "errors": errors, "ok": not errors and all(r["ok"] for r in records)}


def parse_copias(out: str) -> dict:
    secs = sections(out)
    tam = first(secs, "tam")
    disk = (first(secs, "disco") or [""])[0].split()
    snaps = []
    try:
        raw = json.loads("\n".join(first(secs, "snapshots")) or "[]")
    except ValueError:
        raw = None
    for s in raw if isinstance(raw, list) else []:
        try:
            ts = int(datetime.fromisoformat(s["time"][:19] + "+00:00").timestamp())
            sid = s["short_id"]
        except (KeyError, TypeError, ValueError):
            continue
        summ = s.get("summary") or {}
        snaps.append({"id": sid, "at": ts, "tag": (s.get("tags") or [""])[0],
                      "size": summ.get("total_bytes_processed"), "files": summ.get("total_files_processed"),
                      "changed": (summ.get("files_new") or 0) + (summ.get("files_changed") or 0)})
    snaps.sort(key=lambda s: -s["at"])
    fecha = (first(secs, "fecha") or [""])[0]
    return {"last": _ts(fecha) if fecha else None, "size": _int(tam[0]) if tam else None,
            "repo_size": _int(tam[1]) if len(tam) > 1 else None,
            "disk": {"total": _int(disk[1]), "used": _int(disk[2]), "free": _int(disk[3])} if len(disk) > 3 else None,
            "data": [{"name": a, "size": _int(b)} for a, _, b in (x.partition("|") for x in first(secs, "datos"))],
            "with_data": first(secs, "condatos"), "checked_at": _int((first(secs, "comprobado") or ["0"])[0]) or None,
            "snapshots": snaps, "error": raw is None}


def parse_versiones(out: str) -> dict:
    return {a: (None if b == "?" else b) for a, _, b in (x.partition("|") for x in out.split()) if a}


def event_level(text: str) -> str:
    if "❌" in text or "ERROR" in text:
        return "bad"
    if "⚠" in text or "no responde" in text.lower() or "sin responder" in text or "fallida" in text:
        return "warn"
    if "✅" in text or "OK" in text or "recuperada" in text or "☁" in text:
        return "ok"
    return ""


def parse_sucesos(out: str, limit: int = 150) -> list[dict]:
    """El registro, lo más nuevo primero. «AVISO: x» es lo que además se mandó al móvil; se une a su línea gemela."""
    events = []
    for line in out.splitlines():
        m = EVENT_RE.match(line)
        if not m:
            if events and line.strip():
                events[-1]["more"].append(line.strip())
            continue
        text, pushed = m.group(2), False
        if text.startswith("AVISO: "):
            text, pushed = text[7:], True
        events.append({"at": _ts(m.group(1)), "text": text, "pushed": pushed, "level": event_level(text), "more": []})
    for e in events:
        e["more"] = e["more"][:12]
    return events[::-1][:limit]


def human_schedule(spec: list[str]) -> tuple[str, str | None]:
    """Los cinco campos de cron → («cada 5 min» | «cada día a las 02:00» | tal cual, hora «HH:MM» o None)."""
    m, h, dom, mon, dow = spec
    if (dom, mon, dow) == ("*", "*", "*"):
        if h == "*" and m.startswith("*/") and m[2:].isdigit():
            return f"cada {m[2:]} min", None
        if m.isdigit() and h.isdigit():
            at = f"{int(h):02d}:{int(m):02d}"
            return f"cada día a las {at}", at
    return " ".join(spec), None


def parse_crons(out: str) -> dict:
    secs = sections(out)
    beats, now, err = {}, int(time.time()), None
    for line in first(secs, "latidos"):
        k, *v = line.split("|")
        if k == "ahora":
            now = _int(v[0], now)
        elif k == "errores":
            err = {"at": _int(v[0]) or None, "size": _int(v[1]) if len(v) > 1 else 0}
        else:
            beats[k] = (_int(v[0]) or None, v[1] if len(v) > 1 else "")
    lines = first(secs, "crons")
    crons = []
    for cid, (needle, title, desc, risk) in CRONS.items():
        line = next((x for x in lines if needle in x), None)
        c = {"id": cid, "title": title, "desc": desc, "risk": risk, "present": line is not None, "paused": False,
             "schedule": "", "time": None, "last": beats.get("ddns" if cid == "ddns" else cid, (None, ""))[0]}
        if line:
            c["paused"] = line.startswith("#PAUSADO# ")
            c["schedule"], c["time"] = human_schedule(line.removeprefix("#PAUSADO# ").split()[:5])
        if cid == "noche":
            c["last"] = beats.get("copia", (None, ""))[0]
            dep = beats.get("despliegue", (None, ""))
            c["deploy"] = {"at": dep[0], "errors": _int(dep[1]) if dep[1] else 0}
        crons.append(c)
    return {"crons": crons, "now": now, "errors": err}


def parse_job(out: str) -> dict | None:
    """El registro de la última acción → {status, name, lines} como las demás tareas (watchJob)."""
    if out.startswith("@none"):
        return None
    head, _, log = out.partition("\n")
    state, _, name = head.partition("|")
    lines = log.rstrip("\n").splitlines()
    rc = lines[-1][4:].strip() if lines and lines[-1].startswith("@rc ") else None
    if rc is not None:
        lines = lines[:-1]
        while lines and not lines[-1].strip():
            lines.pop()
    if rc == "0":
        status = "ok"
    elif rc is None and state == "@running":
        status = "running"
    else:
        status = "failed"
        if rc is None:
            lines.append("(se cortó antes de terminar)")
    return {"status": status, "name": name, "lines": lines[-400:]}


def _domains(value) -> str:
    doms = value.split() if isinstance(value, str) else [str(x).strip() for x in value or []]
    doms = [d.lower() for d in doms if d]
    if not doms:
        raise ClientesError("hace falta al menos un dominio")
    for d in doms:
        if not DOMAIN_RE.match(d):
            raise ClientesError(f"dominio no válido: {d}")
    if len(set(doms)) != len(doms):
        raise ClientesError("hay un dominio repetido")
    return " ".join(doms)


def _port(value) -> str:
    p = _int(value, -1)
    if not 1024 <= p <= 65535:
        raise ClientesError("el puerto tiene que estar entre 1024 y 65535")
    return str(p)


def _path(value) -> str:
    if not isinstance(value, str) or not PATH_RE.match(value):
        raise ClientesError("la ruta tiene que empezar por / (p. ej. / o /login)")
    return value


def _name(value, extra=()) -> str:
    if not isinstance(value, str) or not (NAME_RE.match(value) or value in extra):
        raise ClientesError("nombre de proyecto no válido")
    return value


def build_action(b: dict) -> list[str]:
    """Lo que pide la app → los argumentos de «panel.sh lanzar», ya comprobados. Las acciones delicadas piden
    además `confirm` con la palabra exacta (el nombre del proyecto, «casa» o «vm»)."""
    a = b.get("action")
    if a in ("copiar", "comprobar-copias", "levantar", "dns-corregir"):
        return [a]
    if a in CONFIRM:
        if b.get("confirm") != CONFIRM[a]:
            raise ClientesError(f"para confirmar hay que escribir «{CONFIRM[a]}»")
        return [a]
    if a == "desplegar":
        return [a, _name(b["name"])] if b.get("name") else [a]
    if a == "reiniciar":
        return [a, _name(b.get("name"), extra=("proxy",))]
    if a in ("quitar", "restaurar"):
        name = _name(b.get("name"))
        if b.get("confirm") != name:
            raise ClientesError(f"para confirmar hay que escribir «{name}»")
        if a == "quitar":
            return [a, name]
        snap = b.get("snapshot")
        if not isinstance(snap, str) or not SNAP_RE.match(snap):
            raise ClientesError("copia no válida")
        return [a, name, snap]
    if a == "editar":
        return [a, _name(b.get("name")), _port(b.get("port")), _path(b.get("path")), _domains(b.get("domains"))]
    if a == "nuevo":
        repo, kind = b.get("repo"), b.get("type")
        if not isinstance(repo, str) or not REPO_RE.match(repo):
            raise ClientesError("el repositorio va como usuario/repo")
        if kind not in ("docker", "web"):
            raise ClientesError("el tipo es docker o web")
        return [a, _name(b.get("name")), repo, kind, _port(b.get("port")), "si" if b.get("data") else "no",
                _path(b.get("path") or "/"), _domains(b.get("domains"))]
    raise ClientesError("acción desconocida")


class Clientes:
    def __init__(self, ssh, script: str):
        if not SCRIPT_RE.match(script):
            raise ClientesError("ruta del script no válida")
        # «~/x» → "$HOME/x": entre comillas la tilde no se expande
        self.script = f'"$HOME/{script[2:]}"' if script.startswith("~/") else shlex.quote(script)
        self.ssh = ssh

    async def sh(self, *args: str, timeout: float = 40) -> str:
        return await self.ssh.run(" ".join([self.script, *(shlex.quote(a) for a in args)]), timeout=timeout)

    async def estado(self) -> dict:
        return parse_estado(await self.sh("estado"))

    async def dns(self) -> dict:
        return parse_dns(await self.sh("dns"))

    async def copias(self) -> dict:
        return parse_copias(await self.sh("copias", timeout=60))

    async def versiones(self) -> dict:
        return parse_versiones(await self.sh("versiones"))

    async def sucesos(self) -> list[dict]:
        return parse_sucesos(await self.sh("sucesos", "400"))

    async def crons(self) -> dict:
        return parse_crons(await self.sh("crons"))

    async def logs(self, name: str, lines: int) -> list[str]:
        out = await self.sh("logs", _name(name, extra=("proxy",)), str(max(10, min(lines, 2000))))
        return out.rstrip("\n").splitlines()

    async def job(self) -> dict | None:
        return parse_job(await self.sh("trabajo"))

    async def run(self, body: dict) -> str:
        out = (await self.sh("lanzar", *build_action(body))).strip()
        state, _, name = out.partition("|")
        if state == "busy":
            raise ClientesError(f"ya hay algo en marcha: {name}")
        if state != "started":
            raise ClientesError(out or "no se pudo arrancar")
        return name

    async def cron(self, body: dict) -> str:
        cid, op = body.get("id"), body.get("op")
        if op == "time":
            if not isinstance(body.get("time"), str) or not TIME_RE.match(body["time"]):
                raise ClientesError("hora no válida")
            args = ["cron-hora", body["time"]]
        elif op in ("pause", "resume") and cid in CRONS:
            args = ["cron-pausar" if op == "pause" else "cron-reanudar", cid]
        else:
            raise ClientesError("cambio no válido")
        out = (await self.sh(*args)).strip()
        if not out.startswith(("hecho", "sin cambios")):
            raise ClientesError(out.splitlines()[0] if out else "no se pudo cambiar el crontab")
        return out.splitlines()[0]
