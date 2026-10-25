from pathlib import Path

from app.modules.raid.raid import parse_raid

OK = (Path(__file__).parent / "fixtures" / "raid_ok.txt").read_text()

DEGRADED = """@mdstat
md0 : active raid5 sde[3] sda[0]
      1953260544 blocks super 1.2 level 5, 512k chunk, algorithm 2 [3/2] [U_U]
      [=>...................]  recovery =  8.6% (84567/976630272) finish=120.5min speed=120000K/sec
@detail
/dev/md0:
        Raid Level : raid5
             State : clean, degraded, recovering
    Active Devices : 2
    Failed Devices : 1
    Rebuild Status : 8% complete

    Number   Major   Minor   RaidDevice State
       0       8        0        0      active sync   /dev/sda
       -       0        0        1      removed
       3       8       64        2      spare rebuilding   /dev/sde

       1       8       16        -      faulty   /dev/sdb
@smart /dev/sdb
SMART overall-health self-assessment test result: FAILED!
  5 Reallocated_Sector_Ct   0x0033   001   001   010    Pre-fail  Always   FAILING_NOW 2048
"""


def test_parse_ok_fixture():
    r = parse_raid(OK)
    assert r["status"] == "ok"
    assert r["level"] == "raid5"
    assert r["pct"] is not None and r["size"] > 0
    devs = {d["dev"]: d for d in r["devices"]}
    assert set(devs) == {"/dev/sda", "/dev/sdb", "/dev/sde"}
    sda = devs["/dev/sda"]
    assert sda["state"] == "active sync"
    assert sda["health"] == "PASSED"
    assert sda["model"] == "ST1000LM024 HN-M101MBB"
    assert sda["temp"] == 37 and sda["hours"] == 17269 and sda["realloc"] == 0 and sda["crc"] == 0
    assert devs["/dev/sdb"]["health"] is None  # sin datos SMART en la muestra


def test_parse_degraded_rebuilding():
    r = parse_raid(DEGRADED)
    assert r["status"] == "rebuilding"
    assert r["progress"] == 8.6
    devs = {d["dev"]: d for d in r["devices"]}
    assert devs["/dev/sdb"]["state"] == "faulty"
    assert devs["/dev/sdb"]["health"] == "FAILED"
    assert devs["/dev/sdb"]["realloc"] == 2048
    assert devs["/dev/sde"]["state"] == "spare rebuilding"
    assert r["problems"]  # hay algo que avisar


def test_parse_degraded_not_rebuilding():
    txt = DEGRADED.replace("clean, degraded, recovering", "clean, degraded").replace("recovery =  8.6%", "")
    assert parse_raid(txt)["status"] == "degraded"


def test_parse_garbage():
    r = parse_raid("ssh: connect to host nas: timeout")
    assert r["status"] == "unknown" and r["devices"] == []


MDSTAT_ONLY_OK = """@mdstat
Personalities : [raid1]
md1 : active raid1 sdc1[1] sdb1[0]
      976630272 blocks super 1.2 [2/2] [UU]

md0 : active raid5 sde[3] sdb[1](F) sda[0]
      1953260544 blocks super 1.2 level 5, 512k chunk, algorithm 2 [3/2] [U_U]
@detail
@df
"""


def test_mdstat_only_healthy_device():
    r = parse_raid(MDSTAT_ONLY_OK, "/dev/md1")
    assert r["status"] == "ok" and r["level"] == "raid1"
    assert [d["dev"] for d in r["devices"]] == ["/dev/sdb1", "/dev/sdc1"]
    assert r["problems"] == []


def test_mdstat_only_degraded_with_faulty():
    r = parse_raid(MDSTAT_ONLY_OK, "/dev/md0")
    assert r["status"] == "degraded" and r["level"] == "raid5"
    devs = {d["dev"]: d["state"] for d in r["devices"]}
    assert devs["/dev/sdb"] == "faulty"
    assert "/dev/sdb marcado como faulty" in r["problems"]


def test_mdstat_only_rebuilding():
    txt = MDSTAT_ONLY_OK.replace("[3/2] [U_U]", "[3/2] [U_U]\n      [=>...]  recovery = 12.5% (1/2) finish=1min")
    r = parse_raid(txt, "/dev/md0")
    assert r["status"] == "rebuilding" and r["progress"] == 12.5


def test_raid_command_local_and_remote():
    from app.modules.raid.raid import raid_command
    local = raid_command({"device": "/dev/md1", "ssh": "", "ssh_options": "", "sudo": True})
    assert "sudo -n mdadm --detail /dev/md1" in local and "ssh" not in local.split("\n")[0]
    remote = raid_command({"device": "/dev/md0", "ssh": "root@nas", "ssh_options": "-i ~/.ssh/k", "sudo": False})
    assert remote.startswith("ssh -o ConnectTimeout=5 -o BatchMode=yes -i ~/.ssh/k root@nas sh -s")
