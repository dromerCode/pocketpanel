"""Una tarea larga (actualizar, restaurar…) con su registro, para seguirla desde la app."""
import logging
import time

log = logging.getLogger("pocketpanel.jobs")


class Job:
    def __init__(self, name: str):
        self.name = name
        self.status = "running"   # running | ok | noop | failed
        self.lines: list[str] = []
        self.started = time.time()

    def log(self, msg: str) -> None:
        log.info("[%s] %s", self.name, msg)
        self.lines.append(f"{time.strftime('%H:%M:%S')}  {msg}")

    def view(self) -> dict:
        return {"name": self.name, "status": self.status, "lines": self.lines[-300:], "started": int(self.started)}
