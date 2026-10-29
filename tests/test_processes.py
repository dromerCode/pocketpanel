import asyncio

import pytest

from app.processes import PROCS_SCRIPT, WARM, ProcessError, Processes, parse_procs, select


def view(out, prev, **kw):
    snap, nxt = parse_procs(out, prev)
    return select(snap, **kw), nxt


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
@cg
/proc/400/cgroup:docker-{cid}
"""
CID = "ab" * 32


def sample(total, a, b):
    return HEAD.format(total=total, a=a, b=b, cid=CID)


def test_first_sample_has_no_cpu_and_skips_kernel_threads():
    r, prev = view(sample(1000, 10, 100), None)
    assert r["count"] == 2  # sin kthreadd ni sus hilos
    assert [p["cpu"] for p in r["procs"]] == [None, None]
    assert prev[0] == 1000


def test_cpu_between_samples_and_names_with_parens():
    _, prev = view(sample(1000, 10, 100), None)
    r, _ = view(sample(1400, 10, 300), prev)  # 400 jiffies en 4 núcleos: 100 por núcleo
    app = r["procs"][0]
    assert app["name"] == "my app (dev)" and app["pid"] == 400
    assert app["cpu"] == 200.0  # 200 ticks = dos núcleos enteros
    assert app["user"] == "ramn" and app["cmd"] == "python3 serve.py --port 9"
    assert app["container"] == CID and r["procs"][1]["container"] is None
    assert app["mem"] == 25000 * 4096
    assert app["mem_pct"] == round(25000 * 4096 * 100 / (1000000 * 1024), 1)
    assert r["procs"][1]["cpu"] == 0.0


def test_reused_pid_does_not_count_old_ticks():
    _, prev = view(sample(1000, 10, 100), None)
    later = sample(1400, 10, 70).replace("0 4 0 77 100", "0 4 0 88 100")  # otro inicio: otro proceso
    r, _ = view(later, prev)
    assert r["procs"][0]["pid"] == 400 and r["procs"][0]["cpu"] == 120.0  # sus 70+50 ticks, sin restar los del viejo


def test_sort_and_filter():
    _, prev = view(sample(1000, 10, 100), None)
    r, _ = view(sample(1400, 10, 300), prev, sort="mem")
    assert [p["pid"] for p in r["procs"]] == [400, 1]
    r, _ = view(sample(1400, 10, 300), prev, q="ROOT")
    assert [p["pid"] for p in r["procs"]] == [1] and r["shown"] == 1 and r["count"] == 2
    r, _ = view(sample(1400, 10, 300), prev, q="400")
    assert [p["pid"] for p in r["procs"]] == [400]


def test_warm_section_gives_cpu_on_first_open():
    warm = "@stat0\ncpu  1000 0 0 0 0 0 0 0 0 0\n@procs0\n" + sample(1000, 10, 100).split("@procs\n")[1].split("@ps")[0]
    r, _ = view(warm + sample(1400, 10, 300), None)
    assert r["procs"][0]["cpu"] == 200.0


class FakeSSH:
    def __init__(self, outs):
        self.outs, self.cmds = list(outs), []

    async def run(self, cmd, timeout=15):
        self.cmds.append(cmd)
        return self.outs.pop(0)


class FakeDocker:
    async def containers(self):
        return [{"Id": CID, "Names": ["/web"]}]


def test_sampler_warms_shares_and_names_containers(monkeypatch):
    import app.processes as mod
    clock = [100.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])
    ssh = FakeSSH([sample(1000, 10, 100), sample(1400, 10, 300)])
    p = Processes(ssh, FakeDocker())
    first = asyncio.run(p.sample())
    assert first["procs"][0]["container"] == "web"
    clock[0] += 2
    asyncio.run(p.sample("mem", "init"))  # otra pantalla: la misma muestra, otro orden y filtro
    assert len(ssh.cmds) == 1
    clock[0] += 3
    r = asyncio.run(p.sample("bogus"))
    assert ssh.cmds == [WARM + PROCS_SCRIPT, PROCS_SCRIPT]
    assert r["sort"] == "cpu" and r["procs"][0]["cpu"] == 200.0


def test_signal():
    ssh = FakeSSH(["@rc 0\n", "bash: kill: (1234) - Operation not permitted\n@rc 1\n"])
    p = Processes(ssh)
    asyncio.run(p.signal(400, "TERM"))
    assert ssh.cmds[0].startswith("kill -s TERM -- 400 ")
    with pytest.raises(ProcessError, match="no es tuyo"):
        asyncio.run(p.signal(1234, "KILL"))
    for pid, sig in ((1, "TERM"), (400, "HUP"), ("400; rm", "TERM")):
        with pytest.raises(ProcessError):
            asyncio.run(p.signal(pid, sig))
