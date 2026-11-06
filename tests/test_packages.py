import asyncio

import pytest

from app.modules.packages.packages import Packages, PackagesError, parse_job, parse_list, run_script

LIST = """
@list
Listing...
bpftool/resolute-updates 7.7.0+7.0.0-42.42 amd64 [upgradable from: 7.7.0+7.0.0-38.38]
openssl/resolute-updates,resolute-security 3.5.1-1ubuntu2 amd64 [upgradable from: 3.5.1-1ubuntu1]
google-chrome-stable/stable 156.0.8078.73-1 amd64 [upgradable from: 156.0.8078.47-1]
@stamp
1793158413
@reboot
yes
linux-image-7.0.0-42-generic
"""


def test_parse_list():
    p = parse_list(LIST)
    assert p["count"] == 3 and p["security"] == 1
    assert p["packages"][1] == {"name": "openssl", "from": "3.5.1-1ubuntu1", "to": "3.5.1-1ubuntu2", "security": True,
                                "held": False, "kept": False}
    assert p["held"] == 0  # sin simulación (falló o apt viejo), todo cuenta
    assert p["checked_at"] == 1793158413
    assert p["reboot"] and p["reboot_pkgs"] == ["linux-image-7.0.0-42-generic"]


def test_parse_list_up_to_date():
    p = parse_list("@list\nListing...\n@stamp\n@reboot\n")
    assert p == {"packages": [], "count": 0, "held": 0, "kept": 0, "kept_security": 0, "security": 0, "checked_at": None,
                 "reboot": False, "reboot_pkgs": []}


def test_parse_list_phasing():
    """Lo que `apt upgrade` aún no instala (phasing) sale en espera, al final, y no cuenta: si contara, el botón de
    actualizar no haría nada y seguiría ahí."""
    out = LIST.replace("@reboot\n", "@inst\nopenssl\n@phased\n  bpftool google-chrome-stable\n@reboot\n")
    p = parse_list(out)
    assert p["count"] == 1 and p["held"] == 2 and p["security"] == 1
    assert [(x["name"], x["held"]) for x in p["packages"]] == [
        ("openssl", False), ("bpftool", True), ("google-chrome-stable", True)]
    p = parse_list(LIST.replace("@reboot\n", "@inst\n@phased\n  bpftool openssl google-chrome-stable\n@reboot\n"))  # todo en espera
    assert p["count"] == 0 and p["held"] == 3 and p["security"] == 0


def test_parse_list_kept_back_is_not_phasing():
    """Lo que apt retiene (dependencias nuevas, apt-mark hold) no se arregla solo: no sale como «en espera»."""
    p = parse_list(LIST + "@inst\nbpftool\n@phased\n  openssl\n@reboot\n")
    assert (p["count"], p["held"], p["kept"]) == (1, 1, 1)
    by = {x["name"]: (x["held"], x["kept"]) for x in p["packages"]}
    assert by == {"bpftool": (False, False), "openssl": (True, False), "google-chrome-stable": (False, True)}
    assert [x["name"] for x in p["packages"]] == ["bpftool", "google-chrome-stable", "openssl"]  # lo tuyo antes


def test_parse_list_kept_back_security_still_warns():
    p = parse_list(LIST + "@inst\n@phased\n  bpftool google-chrome-stable\n@reboot\n")
    assert p["kept"] == 1 and p["kept_security"] == 1 and p["security"] == 0
    p = parse_list(LIST + "@inst\n@phased\n  bpftool  openssl:amd64  google-chrome-stable\n@reboot\n")  # apt 3, por columnas
    assert p["kept"] == 0 and p["held"] == 3 and p["kept_security"] == 0


def test_parse_job():
    assert parse_job("@none\n") is None
    assert parse_job("@running\n$ sudo apt update\nHit:1 x\n") == {"status": "running",
                                                                    "lines": ["$ sudo apt update", "Hit:1 x"]}
    assert parse_job("@done\n$ sudo apt update\n@rc 0\n")["status"] == "ok"
    j = parse_job("@done\n$ sudo apt update\nsudo: a password is required\n@rc 1\n")
    assert j["status"] == "failed" and any("NOPASSWD" in x for x in j["lines"])
    j = parse_job("@done\n$ sudo apt update\n")  # se murió sin llegar al final
    assert j["status"] == "failed" and j["lines"][-1] == "(se cortó antes de terminar)"


def test_run_script_uses_only_the_allowed_commands():
    s = run_script(True)
    assert "sudo -n apt update" in s and "sudo -n apt upgrade -y;" in s and "setsid nohup" in s
    assert "upgrade" not in run_script(False)
    assert 'echo upgrade >' in s and 'echo check >' in run_script(False)


class FakeSSH:
    def __init__(self, answers):
        self.answers, self.cmds = answers, []

    async def run(self, cmd, timeout=15):
        self.cmds.append(cmd)
        return next(a for k, a in self.answers if k in cmd)


def test_packages_cache_and_start():
    ssh = FakeSSH([("apt list", LIST), ("setsid", "started\n"), ("kill -0", "")])
    pk = Packages(ssh)

    async def go():
        a = await pk.listing()
        await pk.listing()
        assert sum("apt list" in c for c in ssh.cmds) == 1 and a["running"] is False and a["doing"] is None
        await pk.start(True)
        await pk.listing()  # al arrancar se olvida la lista
        assert sum("apt list" in c for c in ssh.cmds) == 2
        ssh.answers.insert(0, ("kill -0", "check\n"))
        assert (await pk.listing())["doing"] == "check"
        ssh.answers.insert(0, ("setsid", "busy\n"))
        with pytest.raises(PackagesError):
            await pk.start(False)

    asyncio.run(go())


def test_parse_job_conffile_prompt_hint():
    out = ("@done\n$ sudo apt upgrade -y\ndpkg: error processing package nginx (--configure):\n"
           " end of file on stdin at conffile prompt\n@rc 100\n")
    j = parse_job(out)
    assert j["status"] == "failed" and "  sudo dpkg --configure -a" in j["lines"]
