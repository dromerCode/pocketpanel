import json

from app.tailscale import parse_status


def test_parse_status():
    j = {"BackendState": "Running", "CurrentTailnet": {"Name": "me@example.com"},
         "Self": {"HostName": "server", "DNSName": "server.tail.ts.net.", "TailscaleIPs": ["100.1.1.1", "fd7a::1"],
                  "OS": "linux", "Online": True, "LastSeen": "0001-01-01T00:00:00Z"},
         "Peer": {"a": {"HostName": "phone", "TailscaleIPs": ["fd7a::2", "100.1.1.2"], "OS": "android", "Online": False,
                        "LastSeen": "2026-10-28T13:22:05.1Z"},
                  "b": {"HostName": "laptop", "TailscaleIPs": ["100.1.1.3"], "OS": "linux", "Online": True,
                        "LastSeen": "0001-01-01T00:00:00Z"}}}
    t = parse_status(json.dumps(j))
    assert [d["name"] for d in t["devices"]] == ["server", "laptop", "phone"] and t["online"] == 2
    assert t["devices"][0]["me"] and t["devices"][2]["ip"] == "100.1.1.2" and t["devices"][2]["last_seen"]
    assert t["devices"][1]["last_seen"] is None


def test_not_running():
    assert parse_status("failed to connect to local tailscaled")["state"] == "error"
    assert parse_status(json.dumps({"BackendState": "Stopped"}))["state"] == "Stopped"


def test_falls_back_to_container():
    # si tailscale va en un contenedor: sin el binario se usa docker exec
    from app.tailscale import SCRIPT
    assert "command -v tailscale" in SCRIPT and "docker exec" in SCRIPT and "@absent" in SCRIPT


def test_absent():
    assert parse_status("@absent\n") == {"state": "absent", "devices": []}
