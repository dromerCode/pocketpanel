import asyncio

from app.processes import PROCS_SCRIPT, WARM, Processes, parse_procs

HEAD = """@stat
cpu  {total} 0 0 0 0 0 0 0 0 0
@n
4
@mem
MemTotal:        1000000 kB
@page
4096
@procs
1 (systemd) S 0 1 1 0 -1 4194560 0 0 0 0 {a} 0 0 0 20 0 1 0 5 100 2500 0
2 (kthreadd) S 0 0 0 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 2 0 0 0
30 (kworker/0:1) I 2 0 0 0 -1 0 0 0 0 0 9999 0 0 0 20 0 1 0 9 0 0 0
400 (my app (dev)) R 1 400 400 0 -1 0 0 0 0 0 {b} 50 0 0 20 0 4 0 77 100 25000 0
@ps
      1 root                             /sbin/init splash
    400 ramn                             python3 serve.py --port 9
"""


def sample(total, a, b):
    return HEAD.format(total=total, a=a, b=b)


def test_first_sample_has_no_cpu_and_skips_kernel_threads():
    r, prev = parse_procs(sample(1000, 10, 100), None)
    assert r["count"] == 2  # sin kthreadd ni sus hilos
    assert [p["cpu"] for p in r["procs"]] == [None, None]
    assert prev[0] == 1000


def test_cpu_between_samples_and_names_with_parens():
    _, prev = parse_procs(sample(1000, 10, 100), None)
    r, _ = parse_procs(sample(1400, 10, 300), prev)  # 400 jiffies en 4 núcleos: 100 por núcleo
    app = r["procs"][0]
    assert app["name"] == "my app (dev)" and app["pid"] == 400
    assert app["cpu"] == 200.0  # 200 ticks = dos núcleos enteros
    assert app["user"] == "ramn" and app["cmd"] == "python3 serve.py --port 9"
    assert app["mem"] == 25000 * 4096
    assert app["mem_pct"] == round(25000 * 4096 * 100 / (1000000 * 1024), 1)
    assert r["procs"][1]["cpu"] == 0.0


def test_reused_pid_does_not_count_old_ticks():
    _, prev = parse_procs(sample(1000, 10, 100), None)
    later = sample(1400, 10, 70).replace("0 4 0 77 100", "0 4 0 88 100")  # otro inicio: otro proceso
    r, _ = parse_procs(later, prev)
    assert r["procs"][0]["pid"] == 400 and r["procs"][0]["cpu"] == 120.0  # sus 70+50 ticks, sin restar los del viejo


def test_sort_and_filter():
    _, prev = parse_procs(sample(1000, 10, 100), None)
    r, _ = parse_procs(sample(1400, 10, 300), prev, sort="mem")
    assert [p["pid"] for p in r["procs"]] == [400, 1]
    r, _ = parse_procs(sample(1400, 10, 300), prev, q="ROOT")
    assert [p["pid"] for p in r["procs"]] == [1] and r["shown"] == 1 and r["count"] == 2
    r, _ = parse_procs(sample(1400, 10, 300), prev, q="400")
    assert [p["pid"] for p in r["procs"]] == [400]


def test_warm_section_gives_cpu_on_first_open():
    warm = "@stat0\ncpu  1000 0 0 0 0 0 0 0 0 0\n@procs0\n" + sample(1000, 10, 100).split("@procs\n")[1].split("@ps")[0]
    r, _ = parse_procs(warm + sample(1400, 10, 300), None)
    assert r["procs"][0]["cpu"] == 200.0


class FakeSSH:
    def __init__(self, outs):
        self.outs, self.cmds = list(outs), []

    async def run(self, cmd, timeout=15):
        self.cmds.append(cmd)
        return self.outs.pop(0)


def test_sampler_warms_only_without_recent_sample():
    ssh = FakeSSH([sample(1000, 10, 100), sample(1400, 10, 300)])
    p = Processes(ssh)
    asyncio.run(p.sample())
    r = asyncio.run(p.sample("bogus"))
    assert ssh.cmds == [WARM + PROCS_SCRIPT, PROCS_SCRIPT]
    assert r["sort"] == "cpu" and r["procs"][0]["cpu"] == 200.0
