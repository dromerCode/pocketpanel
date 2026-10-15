import httpx

from app.requirements import check_module, parse_checks, script_for

BK = {"source": "/srv/appdata", "dest": "bk@nas:/backups", "ssh_key": "", "ssh_options": "-p 2222",
      "keep_days": 7, "excludes": [], "at": "04:00"}


class SSH:
    def __init__(self, out):
        self.out, self.cmds = out, []

    async def run(self, cmd, timeout=15):
        self.cmds.append(cmd)
        return self.out


def test_parse_checks():
    out = "basura\nPPCHK|rsync|1|error|\nPPCHK|dest|0|error|ssh: connect to host nas port 2222: refused\n"
    labels = {"rsync": "rsync instalado", "dest": "Entra por SSH en el destino"}
    assert parse_checks(out, labels) == [
        {"label": "rsync instalado", "ok": True, "level": "error", "detail": ""},
        {"label": "Entra por SSH en el destino", "ok": False, "level": "error",
         "detail": "ssh: connect to host nas port 2222: refused"}]


def test_missing_check_counts_as_failed():
    r = parse_checks("", {"rsync": "rsync instalado"})
    assert r == [{"label": "rsync instalado", "ok": False, "level": "error", "detail": "sin respuesta"}]


def test_backup_script_uses_proposed_values():
    s, labels = script_for("backups", BK)
    assert "/srv/appdata" in s and "bk@nas" in s and "-p 2222" in s and "rsync" in s
    assert set(labels) == {"rsync", "source", "dest", "remote_rsync"}


def test_raid_remote_is_wrapped_in_ssh():
    s, _ = script_for("raid", {"device": "/dev/md0", "ssh": "root@nas", "ssh_options": "", "sudo": False})
    assert s.startswith("ssh ") and "root@nas" in s


def test_claude_defaults_to_user_home():
    s, labels = script_for("claude", {"home": "", "cwd": "", "bin": "", "permission_mode": ""})
    assert '"$HOME/.local/bin/claude"' in s and "bin" in labels


async def test_check_module_runs_over_ssh():
    ssh = SSH("PPCHK|tmux|0|warn|\n")
    r = await check_module("terminal", {}, ssh)
    assert r == [{"label": "tmux instalado (para el modo tmux)", "ok": False, "level": "warn", "detail": ""}]


async def test_modules_without_requirements():
    assert await check_module("updates", {"check_at": "05:30"}, SSH("")) == []


async def test_jellyfin_checks_http():
    def handler(req):
        if req.url.path == "/token/login":
            return httpx.Response(200 if req.headers.get("authorization") else 401, json={"token": "t"})
        if req.url.path == "/System/Info/Public":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    vals = {"jfa_url": "http://jfa", "jellyfin_url": "http://jf", "jfa_user": "a", "jfa_pass": "b",
            "public_url": "", "db": ""}
    r = await check_module("jellyfin", vals, SSH(""), http=http)
    assert [x["ok"] for x in r] == [True, True] and r[0]["label"].startswith("jfa-go")


def test_scripts_really_run_in_a_shell(tmp_path):
    import subprocess
    s, labels = script_for("raid", {"device": str(tmp_path), "ssh": "", "ssh_options": "", "sudo": False})
    out = subprocess.run(["bash", "-c", s], capture_output=True, text=True, timeout=20).stdout
    r = {x["label"]: x for x in parse_checks(out, labels)}
    assert r["El dispositivo existe"]["ok"] is True
    s, labels = script_for("raid", {"device": "/no/existe", "ssh": "", "ssh_options": "", "sudo": False})
    out = subprocess.run(["bash", "-c", s], capture_output=True, text=True, timeout=20).stdout
    r = {x["label"]: x for x in parse_checks(out, labels)}
    assert r["El dispositivo existe"] == {"label": "El dispositivo existe", "ok": False, "level": "error",
                                          "detail": "no existe /no/existe"}


async def test_downloads_checks_each_configured_service():
    def handler(req):
        if req.url.host == "qb" and req.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.", headers={"set-cookie": "SID=1"})
        if req.url.host == "qb":
            return httpx.Response(200, json=[])
        if req.url.host == "sonarr":
            return httpx.Response(401)
        return httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    vals = {"qbittorrent_url": "http://qb", "qbittorrent_user": "u", "qbittorrent_pass": "p",
            "sonarr_url": "http://sonarr", "sonarr_key": "x", "radarr_url": "", "radarr_key": "",
            "notify_finished": True}
    r = await check_module("downloads", vals, SSH(""), http=http)
    assert [(x["label"], x["ok"]) for x in r] == [("qBittorrent responde y el usuario es correcto", True),
                                                   ("Sonarr responde y la API key es correcta", False)]
    assert "API key" in r[1]["detail"]
