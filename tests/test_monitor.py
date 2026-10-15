from app.alerts import Alerts
from app.history import HistoryDB


def test_history_add_query_prune(tmp_path):
    db = HistoryDB(str(tmp_path / "h.db"))
    for i in range(10):
        db.add(1000 + i * 30, cpu=10.0 + i, mem=50.0, temp=40.0)
    db.add(1000 + 3600, cpu=None, mem=60.0, temp=None)
    pts = db.query(since=1000, bucket=60)
    assert pts[0] == {"t": 960, "cpu": 10.0, "mem": 50.0, "temp": 40.0}  # 960-1019: solo ts=1000
    assert pts[1]["t"] == 1020 and pts[1]["cpu"] == 11.5  # 1030 y 1060
    assert pts[-1]["cpu"] is None and pts[-1]["mem"] == 60.0
    db.prune(before=1000 + 3600)
    assert len(db.query(since=0, bucket=60)) == 1


def test_container_alerts_transitions():
    a = Alerts()
    assert a.containers({"jellyfin": "running", "sonarr": "running"}, now=0) == []  # estado inicial: sin avisos
    assert a.containers({"jellyfin": "exited", "sonarr": "running"}, now=30) == ["jellyfin se ha parado (exited)"]
    assert a.containers({"jellyfin": "exited", "sonarr": "running"}, now=60) == []  # no se repite
    assert a.containers({"jellyfin": "running", "sonarr": "restarting"}, now=90) == ["sonarr se ha parado (restarting)"]


def test_user_stop_is_quiet():
    a = Alerts()
    a.containers({"radarr": "running"}, now=0)
    a.user_stopped("radarr", now=10)
    assert a.containers({"radarr": "exited"}, now=30) == []
    a.containers({"radarr": "running"}, now=500)
    assert a.containers({"radarr": "exited"}, now=530) == ["radarr se ha parado (exited)"]


def test_removed_container_is_quiet():
    a = Alerts()
    a.containers({"x": "running"}, now=0)
    assert a.containers({}, now=30) == []


def test_disk_threshold_crossing():
    a = Alerts()
    d = lambda pct: [{"mount": "/media/sdd1", "pct": pct}]
    assert a.disks(d(95)) == []          # ya estaba lleno al arrancar: no avisar
    a2 = Alerts()
    assert a2.disks(d(85)) == []
    assert a2.disks(d(91)) == ["Disco sdd1 al 91%"]
    assert a2.disks(d(92)) == []
    assert a2.disks(d(80)) == []
    assert a2.disks(d(90)) == ["Disco sdd1 al 90%"]


def test_raid_problems_only_new():
    a = Alerts()
    assert a.raid({"status": "ok", "problems": []}) == []
    assert a.raid({"status": "degraded", "problems": ["RAID clean, degraded", "/dev/sdb: SMART FAILED"]}) == [
        "RAID clean, degraded", "/dev/sdb: SMART FAILED"]
    assert a.raid({"status": "degraded", "problems": ["RAID clean, degraded", "/dev/sdb: SMART FAILED"]}) == []
    assert a.raid({"status": "unknown", "problems": []}) == []  # NAS inaccesible: no cambia el estado conocido
    assert a.raid({"status": "ok", "problems": []}) == ["RAID recuperado: todo en orden"]


def test_disk_limit_configurable():
    a = Alerts(disk_limit=70)
    d = lambda pct: [{"mount": "/", "pct": pct}]
    a.disks(d(50))
    assert a.disks(d(75)) == ["Disco / al 75%"]
