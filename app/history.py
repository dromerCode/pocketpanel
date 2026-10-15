import sqlite3


class HistoryDB:
    """Muestras del sistema (cpu %, ram %, temperatura) para las gráficas."""

    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS s (ts INTEGER PRIMARY KEY, cpu REAL, mem REAL, temp REAL)")
        self.db.commit()

    def add(self, ts: int, cpu: float | None, mem: float | None, temp: float | None) -> None:
        self.db.execute("INSERT OR REPLACE INTO s VALUES (?,?,?,?)", (ts, cpu, mem, temp))
        self.db.commit()

    def query(self, since: int, bucket: int) -> list:
        rows = self.db.execute(
            "SELECT (ts / ?) * ? AS b, avg(cpu), avg(mem), avg(temp) FROM s WHERE ts >= ? GROUP BY b ORDER BY b",
            (bucket, bucket, since)).fetchall()
        r1 = lambda v: None if v is None else round(v, 1)
        return [{"t": b, "cpu": r1(c), "mem": r1(m), "temp": r1(t)} for b, c, m, t in rows]

    def prune(self, before: int) -> None:
        self.db.execute("DELETE FROM s WHERE ts < ?", (before,))
        self.db.commit()
