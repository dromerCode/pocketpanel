from .system import disk_label

DISK_LIMIT = 90
USER_STOP_GRACE = 120


class Alerts:
    """Decide qué avisar comparando con lo visto antes. Solo transiciones; el primer vistazo no avisa."""

    def __init__(self, disk_limit: int = DISK_LIMIT):
        self.disk_limit = disk_limit
        self._containers: dict[str, str] | None = None
        self._user_stops: dict[str, float] = {}
        self._full_disks: set[str] | None = None
        self._raid_problems: set[str] | None = None

    def user_stopped(self, name: str, now: float) -> None:
        self._user_stops[name] = now

    def containers(self, states: dict[str, str], now: float) -> list[str]:
        prev, self._containers = self._containers, dict(states)
        if prev is None:
            return []
        out = []
        for name, st in states.items():
            if prev.get(name) == "running" and st != "running":
                if now - self._user_stops.get(name, -1e9) > USER_STOP_GRACE:
                    out.append(f"{name} se ha parado ({st})")
        return out

    def disks(self, disks: list) -> list[str]:
        full = {d["mount"] for d in disks if d["pct"] >= self.disk_limit}
        prev, self._full_disks = self._full_disks, full
        if prev is None:
            return []
        out = []
        for d in disks:
            if d["mount"] in full and d["mount"] not in prev:
                out.append(f"Disco {disk_label(d['mount'])} al {d['pct']}%")
        return out

    def raid(self, r: dict) -> list[str]:
        if r["status"] == "unknown":
            return []
        probs = set(r["problems"])
        prev, self._raid_problems = self._raid_problems, probs
        if prev is None:
            return list(r["problems"]) if r["problems"] else []
        if prev and not probs:
            return ["RAID recuperado: todo en orden"]
        return [p for p in r["problems"] if p not in prev]
