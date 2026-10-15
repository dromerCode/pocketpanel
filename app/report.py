import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from .system import SYSTEM_SCRIPT, parse_system

log = logging.getLogger("pocketpanel.report")

PROMPT = """Revisión diaria del servidor (te la pide pocketpanel de forma automática).

Reglas: SOLO LECTURA. No reinicies, no actualices, no borres ni cambies nada; si algo necesita arreglo, dilo y ya
lo decidirá el administrador. Comandos de solo lectura permitidos (docker ps/logs/inspect, df, cat, etc.).

Los datos que ha recogido pocketpanel están en {path} (JSON). Revisa:
1. Salud: contenedores caídos o que se han reiniciado (mira `docker logs --tail 80` de esos para ver por qué),
   temperatura y RAM.
2. Discos y backups: espacio, RAID/SMART si hay datos y si el último backup fue bien (si hay backups).
3. Actualizaciones pendientes: lista corta y avisa si alguna parece arriesgada (salto de versión mayor, base de datos).
{notes}
Cuenta los detalles como quieras y TERMINA con una línea que empiece exactamente por "RESUMEN:" seguida del resumen
para la notificación del móvil: máximo 3 líneas cortas, texto plano sin markdown, español de España, empezando por ✅
si todo está bien o ⚠️ si hay algo que mirar."""


def extract_summary(text: str) -> str:
    """Lo que va después de 'RESUMEN:' (sin markdown, máx. 300 caracteres)."""
    i = text.rfind("RESUMEN:")
    part = text[i + len("RESUMEN:"):] if i >= 0 else text.strip().split("\n\n")[-1]
    part = re.sub(r"[*_`#>]+", "", part).strip()
    part = "\n".join(l.strip() for l in part.splitlines() if l.strip())
    return part[:300] + ("…" if len(part) > 300 else "") or "Revisión hecha"


class Report:
    """Informe diario: recoge datos, se los pasa a Claude (solo lectura) y manda el resumen por push."""

    def __init__(self, ctx, claude, notes: str = ""):
        self.ctx, self.claude, self.notes = ctx, claude, notes.strip()
        self.dir = Path(ctx.cfg.data_dir)
        self.state_file = self.dir / "report.json"
        self.turn: int | None = None  # turno de Claude que es un informe

    def state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, **kw) -> None:
        s = {**self.state(), **kw}
        self.state_file.write_text(json.dumps(s))

    async def collect(self) -> dict:
        ctx = self.ctx
        sysinfo, _ = parse_system(await ctx.ssh.run(SYSTEM_SCRIPT), None, ctx.cfg.disks)
        sysinfo.pop("cpu", None)
        containers = []
        for c in await ctx.docker.containers():
            name = c["Names"][0].lstrip("/")
            info = await ctx.docker.inspect_container(name)
            st = info.get("State", {})
            containers.append({"name": name, "state": c["State"], "status": c["Status"],
                               "restart_count": info.get("RestartCount", 0),
                               "started_at": st.get("StartedAt"), "exit_code": st.get("ExitCode"),
                               "health": (st.get("Health") or {}).get("Status")})
        day = ctx.history.query(since=int(time.time()) - 86400, bucket=3600) if ctx.history else []
        peaks = {k: max((p[k] for p in day if p[k] is not None), default=None) for k in ("cpu", "mem", "temp")}
        raid = None
        if ctx.raid:
            try:
                raid = await ctx.raid.raid(max_age=900)
            except Exception as e:  # noqa: BLE001
                raid = {"error": str(e)}
        b = ctx.backup.state() if ctx.backup else None
        u = ctx.updater
        return {
            "fecha": datetime.now(ctx.tz).isoformat(timespec="minutes"),
            "sistema": sysinfo, "picos_24h": peaks, "contenedores": containers, "raid": raid,
            "backup": {"ultima": b.get("last"), "ultima_ok": b.get("last_ok")} if b is not None else None,
            "actualizaciones": sorted(n for n, r in u.results.items() if r.get("status") == "update") if u else None,
            "actualizaciones_comprobadas": u.checked_at if u else None,
        }

    async def run(self) -> bool:
        """Lanza el informe. False si Claude está ocupado (se reintentará)."""
        if self.claude.running:
            return False
        today = datetime.now(self.ctx.tz).strftime("%Y-%m-%d")
        data = await self.collect()
        path = self.dir / f"informe-{today}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        for old in sorted(self.dir.glob("informe-*.json"))[:-7]:
            old.unlink()
        host_path = f"{self.ctx.cfg.host_dir}/data/{path.name}"
        notes = f"\nNotas del administrador: {self.notes}\n" if self.notes else ""
        await self.claude.send(PROMPT.format(path=host_path, notes=notes), None)
        self.turn = self.claude.turn
        self._save(day=today, started=int(time.time()))
        log.info("informe diario lanzado")
        return True

    def is_report_turn(self, turn: int) -> bool:
        return self.turn is not None and turn == self.turn

    async def finished(self, session: str | None, summary: str) -> None:
        if hasattr(self.claude, "last_text"):
            summary = extract_summary(self.claude.last_text()) or summary
        self.turn = None
        self._save(session=session, summary=summary, finished=int(time.time()))
        await self.ctx.push.send(f"Resumen de {self.ctx.cfg.name}", summary, f"/#claude/{session or ''}")
