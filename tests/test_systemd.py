import json

import pytest

from app.systemd import SystemdError, action_command, logs_command, parse_show, pick, show_script


def units(*rows):
    return json.dumps([{"unit": u, "load": "loaded", "active": a, "sub": s, "description": ""} for u, a, s in rows])


def test_pick_skips_os_plumbing():
    out = ("@system\n" + units(("tailscaled.service", "active", "running"), ("dbus.service", "active", "running"),
                              ("systemd-journald.service", "active", "running"), ("apparmor.service", "active", "exited"),
                              ("mine.service", "active", "exited"), ("broken.service", "failed", "failed"),
                              ("snap.cups.cupsd.service", "inactive", "dead"))
           + "\n@mine\nmine.service\nsnap.cups.cupsd.service\nstopped.service\n"
           + "@user\n" + units(("at-spi-dbus-bus.service", "active", "running"), ("bot.service", "active", "running"))
           + "\n@usermine\nbot.service\n")
    assert pick(out) == [("system", "tailscaled.service"), ("system", "mine.service"), ("system", "broken.service"),
                         ("system", "stopped.service"), ("user", "bot.service")]


def test_show_and_parse():
    s = show_script([("system", "a.service"), ("user", "b.service")])
    assert "systemctl show --timestamp=unix" in s and "systemctl --user show" in s
    out = ("@system\nId=a.service\nDescription=A\nActiveState=active\nSubState=running\nUnitFileState=enabled\n"
           "ActiveEnterTimestamp=@1793293930\nInactiveEnterTimestamp=\nMainPID=42\nMemoryCurrent=1024\nResult=success\n\n"
           "@user\nId=b.service\nActiveState=failed\nSubState=failed\nActiveEnterTimestamp=\n"
           "InactiveEnterTimestamp=@1793290000\nMainPID=0\nMemoryCurrent=[not set]\nResult=exit-code\n")
    a, b = parse_show(out)
    assert a["up"] and a["since"] == 1793293930 and a["pid"] == 42 and a["mem"] == 1024 and a["name"] == "system:a.service"
    assert b["failed"] and not b["up"] and b["since"] == 1793290000 and b["mem"] is None and b["scope"] == "user"


def test_commands_are_safe():
    assert action_command("system", "x.service", "restart").startswith("sudo -n systemctl restart x.service")
    assert action_command("user", "x.service", "stop").startswith("systemctl --user stop x.service")
    assert "journalctl --user-unit" in logs_command("user", "x.service")
    assert "-n 0 -f" in logs_command("system", "x.service")
    for bad in (("system", "x.service; rm -rf /", "stop"), ("root", "x.service", "stop"), ("system", "x.service", "mask"),
                ("system", "x.timer", "stop")):
        with pytest.raises(SystemdError):
            action_command(*bad)
