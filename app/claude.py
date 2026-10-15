import asyncio
import json
import re
import shlex
import time
from pathlib import Path

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_OUTPUT = 8000


def _clip(s: str) -> str:
    return s if len(s) <= MAX_OUTPUT else s[:MAX_OUTPUT] + "…"


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if b.get("type") == "text":
            parts.append(b.get("text", ""))
        elif b.get("type") == "image":
            parts.append("[imagen]")
    return "\n".join(parts)


def _blocks(content, with_text: bool) -> list:
    out = []
    if isinstance(content, str):
        return out
    for b in content or []:
        t = b.get("type")
        if t == "text" and with_text and b.get("text"):
            out.append({"t": "text", "d": b["text"]})
        elif t == "tool_use":
            out.append({"t": "tool", "id": b.get("id"), "name": b.get("name"), "input": b.get("input")})
        elif t == "tool_result":
            out.append({"t": "tool_result", "id": b.get("tool_use_id"),
                        "output": _clip(_result_text(b.get("content"))), "error": bool(b.get("is_error"))})
    return out


def normalize_stream(o: dict) -> list:
    """Un objeto del stream-json de `claude -p` → eventos simples para el móvil."""
    if o.get("parent_tool_use_id"):
        return []
    t = o.get("type")
    if t == "system" and o.get("subtype") == "init":
        return [{"t": "session", "id": o.get("session_id")}]
    if t == "stream_event":
        e = o.get("event") or {}
        d = e.get("delta") or {}
        if e.get("type") == "content_block_delta" and d.get("type") == "text_delta":
            return [{"t": "text", "d": d.get("text", "")}]
        return []
    if t == "assistant":
        # el texto ya llegó por deltas
        return _blocks((o.get("message") or {}).get("content"), with_text=False)
    if t == "user":
        return _blocks((o.get("message") or {}).get("content"), with_text=False)
    if t == "result":
        err = (o.get("result") or o.get("subtype") or "error") if o.get("is_error") else None
        return [{"t": "done", "cost": o.get("total_cost_usd"), "error": err}]
    return []


def _human_text(rec: dict) -> str | None:
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isSidechain"):
        return None
    c = (rec.get("message") or {}).get("content")
    if isinstance(c, list):
        texts = [b.get("text", "") for b in c if b.get("type") == "text"]
        if not texts:
            return None
        c = "\n".join(texts)
    if not isinstance(c, str) or not c.strip() or c.lstrip().startswith("<"):
        return None
    return c


def parse_session_file(lines, before: str | None = None, messages: bool = True) -> dict:
    custom = ai = first = None
    msgs = []
    for line in lines:
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        t = rec.get("type")
        if t == "custom-title" and rec.get("customTitle"):
            custom = rec["customTitle"]
        elif t == "ai-title" and rec.get("aiTitle"):
            ai = rec["aiTitle"]
        if t not in ("user", "assistant") or rec.get("isSidechain") or rec.get("isMeta"):
            continue
        if before and rec.get("timestamp", "") >= before:
            continue
        human = _human_text(rec)
        if human is not None:
            first = first or human
            if messages:
                msgs.append({"t": "user", "d": human})
            continue
        if messages:
            msgs.extend(_blocks((rec.get("message") or {}).get("content"), with_text=(t == "assistant")))
    title = custom or ai or (first.strip().splitlines()[0][:80] if first else None)
    return {"title": title or "(sin título)", "messages": msgs}


def build_cmd(text: str, session: str | None, home: str, cwd: str, bin: str = "", permission_mode: str = "") -> str:
    args = [bin or f"{home}/.local/bin/claude", "-p", text, "--output-format", "stream-json",
            "--verbose", "--include-partial-messages"]
    if permission_mode:
        args += ["--permission-mode", permission_mode]
    if session:
        if not UUID_RE.match(session):
            raise ValueError("id de sesión no válido")
        args += ["--resume", session]
    # $$ es el PID del shell; exec hace que claude herede ese PID → podemos matarlo luego.
    return (f"cd {shlex.quote(cwd)} && echo PID:$$ && "
            f"exec env HOME={shlex.quote(home)} {shlex.join(args)} </dev/null")


class ClaudeManager:
    """Un turno de Claude a la vez; guarda los eventos del turno para quien se conecte tarde."""

    def __init__(self, spawn, home: str = "", cwd: str = "", bin: str = "", permission_mode: str = "", paths=None):
        self.spawn, self.home, self.cwd, self.bin = spawn, home, cwd, bin
        self.permission_mode, self.paths = permission_mode, paths
        self.events: list = []
        self.subs: set[asyncio.Queue] = set()
        self.running = False
        self.session: str | None = None
        self.started_at: str | None = None
        self.proc = None
        self.task: asyncio.Task | None = None
        self.turn = 0
        self.stopping = False
        self.on_finish = None  # callback(session, resumen) al acabar un turno

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.subs.add(q)
        return q

    def unsubscribe(self, q) -> None:
        self.subs.discard(q)

    def snapshot(self) -> list:
        return list(self.events)

    def state(self) -> dict:
        return {"t": "state", "running": self.running, "session": self.session, "turn": self.turn}

    def _emit(self, ev: dict, keep: bool = True) -> None:
        # turn + n permiten al cliente descartar duplicados entre la repetición y el directo
        ev = {**ev, "sid": self.session, "turn": self.turn}
        if keep:
            ev["n"] = len(self.events)
            self.events.append(ev)
        for q in self.subs:
            q.put_nowait(ev)

    async def send(self, text: str, session: str | None) -> None:
        if self.running:
            raise RuntimeError("ya hay un turno en marcha")
        if self.paths:  # rutas resueltas en el host (HOME del usuario si la config no dice otra cosa)
            r = await self.paths.resolve()
            self.home, self.cwd, self.bin = r["home"], r["cwd"], r["bin"]
        cmd = build_cmd(text, session, self.home, self.cwd, self.bin, self.permission_mode)
        self.running = True
        self.session = session
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        self.events = []
        self.stopping = False
        self.turn += 1
        self._emit({"t": "user", "d": text})
        self.task = asyncio.create_task(self._run(cmd))

    async def _run(self, cmd: str) -> None:
        done = False
        try:
            self.proc = await self.spawn(cmd)
            async for line in self.proc.lines():
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                for ev in normalize_stream(obj):
                    if ev["t"] == "done" and self.stopping:
                        ev = {"t": "stopped"}
                    if ev["t"] == "session":
                        self.session = ev["id"]
                    done = done or ev["t"] in ("done", "stopped")
                    self._emit(ev)
            code, err = await self.proc.wait()
            if not done and self.stopping:
                self._emit({"t": "stopped"})
            elif not done:
                self._emit({"t": "error", "msg": (err or "").strip()[-1500:] or f"claude terminó con código {code}"})
        except Exception as e:  # noqa: BLE001
            self._emit({"t": "error", "msg": f"{type(e).__name__}: {e}"})
        finally:
            self.running = False
            self.proc = None
            self._emit({"t": "idle"}, keep=False)
            if self.on_finish:
                self.on_finish(self.session, self.summary())

    def last_text(self) -> str:
        """Texto completo del último bloque de respuesta de Claude en este turno."""
        last = ""
        for e in self.events:
            if e["t"] == "text":
                last += e["d"]
            elif e["t"] in ("tool", "user"):
                last = ""
        return last

    def summary(self) -> str:
        """Último bloque de texto de Claude (o el error) para la notificación."""
        last = ""
        for e in self.events:
            if e["t"] == "text":
                last += e["d"]
            elif e["t"] in ("tool", "user"):
                last = ""
            elif e["t"] == "error" or (e["t"] == "done" and e.get("error")):
                return f"Error: {e.get('msg') or e.get('error')}"
            elif e["t"] == "stopped":
                return "Parado"
        last = " ".join(last.split())
        return (last[:140] + "…") if len(last) > 140 else (last or "Listo")

    async def stop(self) -> None:
        if self.proc:
            self.stopping = True
            await self.proc.stop()


class ClaudePaths:
    """Dónde está Claude en el host. Vacío en la config = HOME del usuario del host (se pregunta por SSH una vez)."""

    def __init__(self, ssh, opts: dict, env_home: str = "", env_cwd: str = ""):
        self.ssh, self.opts, self.env_home, self.env_cwd = ssh, opts, env_home, env_cwd
        self._r: dict | None = None

    async def resolve(self) -> dict:
        if self._r is None:
            home = self.opts.get("home") or self.env_home
            if not home:
                home = (await self.ssh.run('printf %s "$HOME"')).strip()
            cwd = self.opts.get("cwd") or self.env_cwd or home
            self._r = {"home": home, "cwd": cwd, "bin": self.opts.get("bin") or f"{home}/.local/bin/claude",
                       # Claude Code guarda las sesiones en projects/<carpeta con lo que no es letra o número → ->
                       "sessions": f"{home}/.claude/projects/{re.sub(r'[^A-Za-z0-9]', '-', cwd)}"}
        return self._r


def _missing(e: Exception) -> bool:
    from asyncssh import SFTPNoSuchFile
    return isinstance(e, (FileNotFoundError, SFTPNoSuchFile))


class LocalFS:
    async def listdir(self, folder: str) -> list:
        return [(p.name, p.stat().st_mtime, p.stat().st_size) for p in Path(folder).iterdir()]

    async def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8", errors="replace")


class SftpFS:
    """Los ficheros del host por SFTP, sobre la misma conexión SSH del panel."""

    def __init__(self, ssh):
        self.ssh = ssh

    async def listdir(self, folder: str) -> list:
        async with (await self.ssh.conn()).start_sftp_client() as sftp:
            return [(n.filename, n.attrs.mtime or 0, n.attrs.size or 0) for n in await sftp.readdir(folder)]

    async def read_text(self, path: str) -> str:
        async with (await self.ssh.conn()).start_sftp_client() as sftp:
            async with sftp.open(path, "rb") as f:
                return (await f.read()).decode("utf-8", errors="replace")


class SessionStore:
    """Lee las conversaciones guardadas por Claude (.jsonl), con caché por mtime/tamaño."""

    def __init__(self, fs, folder):
        self.fs, self.folder = fs, folder  # folder: corrutina que devuelve la carpeta
        self._titles: dict[str, tuple] = {}

    async def list(self, limit: int = 60) -> list:
        d = await self.folder()
        try:
            entries = await self.fs.listdir(d)
        except Exception as e:  # noqa: BLE001
            if _missing(e):  # aún no hay sesiones en esa carpeta
                return []
            raise
        files = sorted((e for e in entries if e[0].endswith(".jsonl") and e[2] > 0), key=lambda e: e[1], reverse=True)
        out = []
        for name, mtime, size in files[:limit]:
            sid = name[:-len(".jsonl")]
            cached = self._titles.get(sid)
            if not cached or cached[0] != (mtime, size):
                text = await self.fs.read_text(f"{d}/{name}")
                cached = ((mtime, size), parse_session_file(text.splitlines(), messages=False)["title"])
                self._titles[sid] = cached
            out.append({"id": sid, "title": cached[1], "updated": int(mtime)})
        return out

    async def read(self, sid: str, before: str | None = None) -> dict | None:
        if not UUID_RE.match(sid):
            return None
        d = await self.folder()
        try:
            text = await self.fs.read_text(f"{d}/{sid}.jsonl")
        except Exception as e:  # noqa: BLE001
            if _missing(e):
                return None
            raise
        return parse_session_file(text.splitlines(), before=before)
