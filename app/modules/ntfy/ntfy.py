"""Temas de ntfy: el panel pregunta por lo nuevo (poll) y guarda los últimos mensajes en data/ntfy.json.

No deja ninguna conexión abierta. Pregunta al abrir Estado (y cada 30 s mientras se mira) y, de fondo, cada 10 min
para no perder nada (ntfy.sh guarda los mensajes 12 h), o cada 30 s si hay que avisar al móvil de cada uno."""
import asyncio
import json
import os
import re
import time
from pathlib import Path

import httpx

TOPIC = re.compile(r"^[-_A-Za-z0-9]{1,64}$")
MAX_TOPICS = 20
KEEP = 100       # mensajes guardados por tema
MARGIN = 60      # s que se vuelven a pedir por si el reloj del servidor va por detrás (lo repetido se descarta)
URL = ("http://", "https://")


class NtfyError(Exception):
    pass


def topic_of(text: str) -> str:
    """El tema, escrito tal cual o pegando su URL (https://ntfy.sh/mitema, ntfy.sh/mitema)."""
    t = (text or "").strip().rstrip("/").rsplit("/", 1)[-1]
    if not TOPIC.match(t):
        raise NtfyError("un tema solo lleva letras, números, - y _ (hasta 64)")
    return t


def _link(v) -> str:
    v = str(v or "")
    return v if v.startswith(URL) else ""


def _int(v, default: int) -> int:
    try:
        return int(v or default)
    except (TypeError, ValueError):
        return default


def parse(text: str) -> list[dict]:
    """Los mensajes de una respuesta de ntfy (un JSON por línea); lo que no es un mensaje (open, keepalive…) se ignora."""
    out = []
    for line in text.splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if not isinstance(m, dict) or m.get("event") != "message" or not m.get("id"):
            continue
        att = m.get("attachment") if isinstance(m.get("attachment"), dict) else {}
        tags = m.get("tags") if isinstance(m.get("tags"), list) else []
        out.append({
            "id": str(m["id"]), "time": _int(m.get("time"), 0), "topic": str(m.get("topic") or ""),
            "title": str(m.get("title") or ""), "message": str(m.get("message") or ""),
            "priority": _int(m.get("priority"), 3),
            "tags": [t for t in tags if isinstance(t, str)],
            "click": _link(m.get("click")),
            "attachment": {"name": str(att.get("name") or "adjunto"), "url": _link(att.get("url"))}
            if _link(att.get("url")) else None,
        })
    return out


def _http_error(r: httpx.Response) -> str:
    if r.status_code in (401, 403):
        return "el servidor no deja leer estos temas: pon el token en ⚙ → Módulos → ntfy"
    if r.status_code == 429:
        return "ntfy pide esperar un poco (demasiadas peticiones)"
    try:
        detail = r.json().get("error")
    except (ValueError, AttributeError):
        detail = None
    return f"ntfy respondió {r.status_code}" + (f": {detail}" if detail else "")


class Ntfy:
    def __init__(self, data_dir: str, server: str, token: str = "", http: httpx.AsyncClient | None = None,
                 now=time.time):
        self.path = Path(data_dir) / "ntfy.json"
        self.server = (server or "https://ntfy.sh").strip().rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = http or httpx.AsyncClient(timeout=15)
        self.now = now
        s = self._read()
        self.topics: list[str] = [t for t in s.get("topics") or [] if isinstance(t, str) and TOPIC.match(t)]
        self.messages: list[dict] = [m for m in s.get("messages") or [] if isinstance(m, dict) and m.get("id")]
        self.since: dict = {t: v for t, v in (s.get("since") or {}).items() if t in self.topics}
        self.error: str | None = None
        self.checked = 0.0
        self._lock = asyncio.Lock()

    def _read(self) -> dict:
        try:
            s = json.loads(self.path.read_text())
            return s if isinstance(s, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        """Atómico y solo para el dueño: en ntfy.sh el nombre del tema es lo único que protege sus mensajes."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(".ntfy.json.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"topics": self.topics, "since": self.since, "messages": self.messages}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def view(self, limit: int = 60) -> dict:
        msgs = sorted(self.messages, key=lambda m: m.get("time", 0), reverse=True)[:limit]
        return {"server": self.server, "topics": self.topics, "messages": msgs, "error": self.error,
                "checked": int(self.checked) or None}

    async def add(self, text: str) -> str:
        t = topic_of(text)
        async with self._lock:
            if t not in self.topics:
                if len(self.topics) >= MAX_TOPICS:
                    raise NtfyError(f"como mucho {MAX_TOPICS} temas")
                self.topics.append(t)
                self._save()
        return t

    async def remove(self, topic: str) -> None:
        async with self._lock:
            if topic in self.topics:
                self.topics.remove(topic)
            self.since.pop(topic, None)
            self.messages = [m for m in self.messages if m.get("topic") != topic]
            self._save()

    async def poll(self, max_age: float = 0) -> list[dict]:
        """Trae lo nuevo de todos los temas (si lo último que se trajo tiene más de `max_age` s) y devuelve los
        mensajes que no se habían visto. Lo que ya estaba en ntfy al suscribirse a un tema se guarda pero no se
        devuelve: no es nuevo, y avisar de todo eso de golpe sería ruido."""
        async with self._lock:
            if not self.topics or self.now() - self.checked < max_age:
                return []
            start, topics = self.now(), list(self.topics)
            first = {t for t in topics if t not in self.since}
            since = "all" if first else str(int(min(self.since[t] for t in topics)) - MARGIN)
            self.checked = start
            try:
                r = await self.http.get(f"{self.server}/{','.join(topics)}/json",
                                        params={"poll": "1", "since": since}, headers=self.headers)
            except httpx.HTTPError as e:
                self.error = f"no se pudo hablar con {self.server}: {str(e) or type(e).__name__}"
                return []
            if r.status_code >= 400:
                self.error = _http_error(r)
                return []
            self.error = None
            seen = {m["id"] for m in self.messages}
            new = [m for m in parse(r.text) if m["id"] not in seen and m["topic"] in topics]
            # con «all» (un tema nuevo) también vuelve lo viejo de los demás que ya se recortó: tampoco es nuevo
            fresh = [m for m in new if m["topic"] not in first and m["time"] >= self.since[m["topic"]] - MARGIN]
            for t in topics:
                self.since[t] = int(start)
            if new:
                self.messages = self._trim(self.messages + new)
            self._save()
            return sorted(fresh, key=lambda m: m["time"])

    @staticmethod
    def _trim(msgs: list[dict]) -> list[dict]:
        """Los KEEP más recientes de cada tema."""
        out, per = [], {}
        for m in sorted(msgs, key=lambda m: m.get("time", 0), reverse=True):
            per[m.get("topic")] = per.get(m.get("topic"), 0) + 1
            if per[m.get("topic")] <= KEEP:
                out.append(m)
        return out[::-1]
