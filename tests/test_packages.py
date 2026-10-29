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
    assert p["packages"][1] == {"name": "openssl", "from": "3.5.1-1ubuntu1", "to": "3.5.1-1ubuntu2", "security": True}
    assert p["checked_at"] == 1793158413
    assert p["reboot"] and p["reboot_pkgs"] == ["linux-image-7.0.0-42-generic"]


def test_parse_list_up_to_date():
    p = parse_list("@list\nListing...\n@stamp\n@reboot\n")
    assert p == {"packages": [], "count": 0, "security": 0, "checked_at": None, "reboot": False, "reboot_pkgs": []}


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
        assert sum("apt list" in c for c in ssh.cmds) == 1 and a["running"] is False
        await pk.start(True)
        await pk.listing()  # al arrancar se olvida la lista
        assert sum("apt list" in c for c in ssh.cmds) == 2
        ssh.answers.insert(0, ("setsid", "busy\n"))
        with pytest.raises(PackagesError):
            await pk.start(False)

    asyncio.run(go())


def test_parse_job_conffile_prompt_hint():
    out = ("@done\n$ sudo apt upgrade -y\ndpkg: error processing package nginx (--configure):\n"
           " end of file on stdin at conffile prompt\n@rc 100\n")
    j = parse_job(out)
    assert j["status"] == "failed" and "  sudo dpkg --configure -a" in j["lines"]
