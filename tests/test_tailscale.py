import json
import shutil
import subprocess

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


STATUS = json.dumps({"BackendState": "Running", "Self": {"HostName": "server", "Online": True}})


def test_warning_around_the_json_is_ignored():
    pretty = json.dumps(json.loads(STATUS), indent=2)
    assert parse_status(f"Warning: client version != tailscaled\n{pretty}\nmás ruido\n")["state"] == "Running"


def run_script(tmp_path, docker: str | None = None, host: str | None = None) -> dict:
    """Ejecuta el script de verdad con un PATH de mentira: `docker` y `tailscale` son cuerpos de sh."""
    from app.tailscale import SCRIPT
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "awk").symlink_to(shutil.which("awk"))
    for name, body in (("docker", docker), ("tailscale", host)):
        if body is not None:
            f = bin_dir / name
            f.write_text("#!/bin/sh\n" + body + "\n")
            f.chmod(0o755)
    (tmp_path / "status.json").write_text(json.dumps(json.loads(STATUS), indent=2) + "\n")
    r = subprocess.run(["/bin/sh", "-c", SCRIPT], env={"PATH": str(bin_dir), "STATUS": str(tmp_path / "status.json")},
                       capture_output=True, text=True, timeout=10)
    return parse_status(r.stdout)


def fake_docker(ps: str, cli_in: str = "") -> str:
    """`docker ps` imprime `ps`; `docker exec` solo funciona en los contenedores de `cli_in`."""
    return f"""case "$1" in
  ps) printf '{ps}' ;;
  exec) case " {cli_in} " in *" $2 "*) [ "$4" = version ] && exit 0
          while IFS= read -r l; do echo "$l"; done < "$STATUS" ;;
        *) echo "exec failed: tailscale not found" >&2; exit 126 ;; esac ;;
esac"""


def test_no_docker_and_no_binary_is_absent(tmp_path):
    assert run_script(tmp_path)["state"] == "absent"


def test_no_tailscale_container_is_absent(tmp_path):
    assert run_script(tmp_path, fake_docker("a1 nginx:latest running\\n"))["state"] == "absent"


def test_container_without_the_cli_is_absent(tmp_path):
    assert run_script(tmp_path, fake_docker("x1 foo/tailscale-exporter running\\n"))["state"] == "absent"


def test_uses_the_container_that_has_the_cli(tmp_path):
    ps = "x1 foo/tailscale-exporter running\\nt1 tailscale/tailscale:latest running\\n"
    assert run_script(tmp_path, fake_docker(ps, "t1"))["state"] == "Running"


def test_docker_failing_is_not_absent(tmp_path):
    t = run_script(tmp_path, "echo 'permission denied' >&2; exit 1")
    assert t["state"] == "error" and "docker" in t["error"]


def test_stopped_container_is_not_absent(tmp_path):
    t = run_script(tmp_path, fake_docker("t1 tailscale/tailscale:latest exited\\n"))
    assert t["state"] == "error" and "parado" in t["error"]


def test_host_binary_with_a_warning(tmp_path):
    body = 'echo "Warning: version mismatch" >&2; while IFS= read -r l; do echo "$l"; done < "$STATUS"'
    assert run_script(tmp_path, host=body)["state"] == "Running"
