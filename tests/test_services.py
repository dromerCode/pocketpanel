from app.docker_api import cpu_percent, demux, mem_usage
from app.services import build_services


def c(name, state="running", ports=None, labels=None):
    return {"Id": name + "id", "Names": ["/" + name], "State": state, "Status": "Up 2 hours",
            "Ports": ports or [], "Labels": labels or {}}


def test_infers_first_public_tcp_port():
    ports = [{"PrivatePort": 7359, "Type": "udp", "PublicPort": 7359},
             {"PrivatePort": 8096, "Type": "tcp", "PublicPort": 8097, "IP": "0.0.0.0"},
             {"PrivatePort": 8096, "Type": "tcp", "PublicPort": 8097, "IP": "::"}]
    s = build_services([c("jellyfin", ports=ports)], {}, {})
    assert s[0]["port"] == 8097 and s[0]["url"] is None


def test_no_ports_means_no_link():
    s = build_services([c("homeassistant")], {}, {})
    assert s[0]["port"] is None and s[0]["url"] is None


def test_override_wins_and_hidden_excluded():
    ov = {"homeassistant": {"port": 8123, "name": "Home Assistant"},
          "tailscale": {"hidden": True},
          "x": {"url": "https://x.example/"}}
    s = build_services([c("homeassistant"), c("tailscale"), c("x", ports=[{"PrivatePort": 1, "PublicPort": 2, "Type": "tcp"}])], {}, ov)
    by = {x["name"]: x for x in s}
    assert "tailscale" not in by
    assert by["homeassistant"]["port"] == 8123 and by["homeassistant"]["title"] == "Home Assistant"
    assert by["x"]["url"] == "https://x.example/"


def test_icon_label_and_stats_and_sorting():
    s = build_services([c("b", labels={"icon": "http://i/b.png"}), c("a", state="exited")],
                       {"bid": {"cpu": 1.5, "mem": 1024}}, {})
    assert [x["name"] for x in s] == ["a", "b"]  # orden por título visible
    assert s[1]["icon"] == "http://i/b.png" and s[1]["cpu"] == 1.5 and s[1]["mem"] == 1024
    assert s[0]["up"] is False and s[0]["cpu"] is None


def test_cpu_percent():
    prev = {"cpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000, "online_cpus": 4}}
    cur = {"cpu_stats": {"cpu_usage": {"total_usage": 200}, "system_cpu_usage": 2000, "online_cpus": 4}}
    assert cpu_percent(prev, cur) == 40.0
    assert cpu_percent(None, cur) is None
    assert cpu_percent(cur, cur) == 0.0


def test_mem_usage_subtracts_inactive_file():
    assert mem_usage({"memory_stats": {"usage": 1000, "stats": {"inactive_file": 300}}}) == 700
    assert mem_usage({"memory_stats": {}}) is None


def test_demux():
    frame = lambda st, b: bytes([st, 0, 0, 0]) + len(b).to_bytes(4, "big") + b
    buf = frame(1, b"hola\n") + frame(2, b"err\n") + frame(1, b"par")
    out, rest = demux(buf)
    assert out == b"hola\nerr\npar" and rest == b""
    out, rest = demux(frame(1, b"abc")[:6])
    assert out == b"" and len(rest) == 6
