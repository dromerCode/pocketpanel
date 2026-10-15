from app.system import disk_label, parse_system

SAMPLE = """@stat
cpu  100 0 100 800 0 0 0 0 0 0
@mem
MemTotal:       14238648 kB
MemAvailable:    7119324 kB
@up
93600.50 1000.00
@load
0.52 0.40 0.30 1/500 1234
@temp
k10temp 45250
@df
Filesystem 1-blocks Used Available Capacity Mounted on
/dev/root 1758724096 1758724096 0 100% /
tmpfs 7290179584 23543808 7266635776 1% /tmp
/dev/nvme0n1p8 475498909696 227302731776 248179400704 48% /srv
/dev/sdb 240057409536 85051473920 153101910016 36% /media/SSD240
//10.0.0.5/nas 1967591211008 4336558080 1963254652928 1% /media/nas/Mi Raid
"""


def test_parse_basic():
    r, cpu = parse_system(SAMPLE, None, ["/srv", "/media/*"])
    assert r["cpu"] is None  # primera muestra
    assert cpu == (1000, 800)
    assert r["mem"]["total"] == 14238648 * 1024
    assert r["mem"]["used"] == (14238648 - 7119324) * 1024
    assert r["uptime"] == 93600
    assert r["load"] == [0.52, 0.40, 0.30]
    assert r["temp"] == 45.2
    mounts = [d["mount"] for d in r["disks"]]
    assert mounts == ["/srv", "/media/SSD240", "/media/nas/Mi Raid"]
    assert r["disks"][0]["pct"] == 48


def test_cpu_between_samples():
    _, prev = parse_system(SAMPLE, None)
    later = SAMPLE.replace("cpu  100 0 100 800", "cpu  150 0 150 900")
    r, _ = parse_system(later, prev)
    assert r["cpu"] == 50.0


def test_missing_temp_and_garbage():
    s = SAMPLE.replace("@temp\nk10temp 45250\n", "@temp\n")
    r, _ = parse_system(s, None)
    assert r["temp"] is None
    r, _ = parse_system("basura", None)
    assert r["disks"] == [] and r["mem"] is None


def test_default_disks_are_real_devices():
    r, _ = parse_system(SAMPLE, None)
    assert [d["mount"] for d in r["disks"]] == ["/", "/srv", "/media/SSD240"]


def test_default_disks_skip_boot_and_snap():
    s = SAMPLE + "/dev/sda1 1000 10 990 1% /boot/efi\n/dev/loop3 1000 1000 0 100% /snap/core/1\n"
    r, _ = parse_system(s, None)
    assert "/boot/efi" not in [d["mount"] for d in r["disks"]]
    assert "/snap/core/1" not in [d["mount"] for d in r["disks"]]


def test_temp_coretemp_preferred_over_acpitz():
    s = SAMPLE.replace("k10temp 45250", "acpitz 27800\ncoretemp 51000")
    r, _ = parse_system(s, None)
    assert r["temp"] == 51.0


def test_temp_unknown_sensor_used_as_fallback():
    s = SAMPLE.replace("k10temp 45250", "nvme 38850")
    r, _ = parse_system(s, None)
    assert r["temp"] == 38.8


def test_disk_label():
    assert disk_label("/") == "/"
    assert disk_label("/srv") == "srv"
    assert disk_label("/media/SSD240") == "SSD240"
