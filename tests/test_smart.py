import asyncio
import json
from datetime import datetime

import pytest

from app.smart import DiskHealth, SmartError, due, parse_disk, parse_health


def smart(**kw):
    j = {"smartctl": {"exit_status": 0}, "model_name": "Disco", "serial_number": kw.pop("serial", "S1"),
         "smart_status": {"passed": kw.pop("passed", True)}, "temperature": {"current": kw.pop("temp", 35)},
         "power_on_time": {"hours": 1000}, "rotation_rate": 5400,
         "ata_smart_attributes": {"table": [{"id": i, "raw": {"value": kw.pop(k, 0)}}
                                            for i, k in ((5, "realloc"), (197, "pending"), (198, "unc"), (199, "crc"),
                                                         (194, "packed"))]},
         "ata_smart_self_test_log": {"standard": {"table": [{"type": {"string": "Short offline"},
                                                             "status": {"string": "Completed without error",
                                                                        "passed": kw.pop("test_ok", True)},
                                                             "lifetime_hours": 990}]}}}
    return json.dumps(j)


def test_levels():
    assert parse_disk("/dev/sda", smart(), 55)["level"] == "ok"
    d = parse_disk("/dev/sda", smart(realloc=1, crc=6, packed=47244640288), 55)
    assert d["level"] == "warn" and d["crc"] == 6 and d["temp"] == 35 and len(d["problems"]) == 1
    assert parse_disk("/dev/sda", smart(temp=60), 55)["level"] == "warn"
    for bad in ({"pending": 2}, {"unc": 1}, {"passed": False}, {"test_ok": False}):
        assert parse_disk("/dev/sda", smart(**bad), 55)["level"] == "bad"
    asleep = json.dumps({"smartctl": {"exit_status": 2, "messages": [{"string": "Device is in STANDBY mode, exit(2)"}]}})
    assert parse_disk("/dev/sda", asleep, 55)["asleep"]
    assert parse_disk("/dev/sdd", "", 55)["level"] == "unknown"


def test_parse_health_maps_mounts_to_disks():
    out = ("@map\n/dev/loop0 loop 4096 /snap/x\n/dev/sda1 part 100 /dev/sda /mnt/sd1\n/dev/sdc disk 100  /mnt/sd2\n"
           f"@sudo yes\n@disk /dev/sda\n{smart()}\n@disk /dev/sdc\n{smart(serial='S2')}\n")
    h = parse_health(out, 55)
    assert h["sudo"] and h["mounts"] == {"/mnt/sd1": "/dev/sda", "/mnt/sd2": "/dev/sdc"}
    assert [d["dev"] for d in h["disks"]] == ["/dev/sda", "/dev/sdc"]


def test_due():
    sun = datetime(2026, 11, 1, 3, 30)  # domingo, día 1
    mon = datetime(2026, 11, 2, 3, 30)
    assert due("weekly", sun, "03:00", None) and not due("weekly", mon, "03:00", None)
    assert due("monthly", sun, "03:00", None) and not due("monthly", mon, "03:00", None)
    assert due("daily", mon, "03:00", None) and not due("daily", mon, "04:00", None)
    assert not due("daily", mon, "03:00", "2026-11-02") and not due("off", sun, "03:00", None)


class FakeSSH:
    def __init__(self, out):
        self.out, self.cmds = out, []

    async def run(self, cmd, timeout=15):
        self.cmds.append(cmd)
        return self.out if "lsblk" in cmd else "Testing has begun.\n@rc 0\n"


def test_alerts_only_when_it_gets_worse(tmp_path):
    ssh = FakeSSH(f"@sudo yes\n@disk /dev/sda\n{smart(crc=1)}\n")
    h = DiskHealth(ssh, str(tmp_path))

    async def look():
        return h.changes(await h.health(max_age=0))

    assert asyncio.run(look()) == []  # la primera vez solo se apunta
    assert asyncio.run(look()) == []
    ssh.out = f"@sudo yes\n@disk /dev/sda\n{smart(crc=3, pending=1)}\n"
    msgs = asyncio.run(look())
    assert any("pendientes 0 → 1" in m for m in msgs) and any("cable" in m for m in msgs)
    # lo visto se guarda: otro DiskHealth (un reinicio del panel) no repite
    h = DiskHealth(ssh, str(tmp_path))
    assert asyncio.run(look()) == []
    h.set_settings({"notify": False})
    ssh.out = f"@sudo yes\n@disk /dev/sda\n{smart(crc=9, pending=1)}\n"
    assert asyncio.run(look()) == []


def test_settings_and_tests(tmp_path):
    h = DiskHealth(FakeSSH(""), str(tmp_path))
    assert h.set_settings({"temp_limit": 50, "short": "daily", "long": "off", "at": "02:30"})["temp_limit"] == 50
    for bad in ({"temp_limit": 200}, {"short": "monthly"}, {"at": "25:00"}, {"temp_limit": True}):
        with pytest.raises(SmartError):
            h.set_settings(bad)
    assert DiskHealth(FakeSSH(""), str(tmp_path)).settings["at"] == "02:30"
    asyncio.run(h.start_test("/dev/sda", "short"))
    assert "smartctl -t short /dev/sda" in h.ssh.cmds[-1]
    for dev, kind in (("/dev/sda; rm -rf /", "short"), ("/dev/sda", "conveyance"), ("/etc/passwd", "long")):
        with pytest.raises(SmartError):
            asyncio.run(h.start_test(dev, kind))
