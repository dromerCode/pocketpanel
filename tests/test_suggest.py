import asyncio

from app.suggest import Container, Env, app_root, suggest_module
from tests.test_modules import client


def ctr(name, image, ports=(), mounts=(), net="bridge", labels=None, state="running"):
    return {"Names": [f"/{name}"], "Image": image, "State": state, "HostConfig": {"NetworkMode": net},
            "Labels": labels or {},
            "Ports": [{"PrivatePort": a, "PublicPort": b, "Type": "tcp"} for a, b in ports],
            "Mounts": [{"Type": "bind", "Source": s, "Destination": d} for s, d in mounts]}


CONTAINERS = [
    ctr("qbittorrent", "ghcr.io/hotio/qbittorrent:release", [(8080, 8181)],
        [("/disk/downloads", "/downloads"), ("/srv/appdata/qbittorrent-ssd/config", "/config")]),
    ctr("sonarr", "lscr.io/linuxserver/sonarr:latest", [(8989, 8989)], [("/srv/appdata/sonarr", "/config")]),
    ctr("radarr", "lscr.io/linuxserver/radarr:latest", net="host", mounts=[("/srv/appdata/radarr", "/config")]),
    ctr("jellyfin", "linuxserver/jellyfin:10", [(8096, 8097)], [("/srv/appdata/jellyfin/config", "/config")]),
    ctr("proxy", "jc21/nginx-proxy-manager:2", [(81, 81)], [("/opt/npm/data", "/data")]),
    ctr("web", "nginx:alpine", labels={"traefik.http.routers.web.rule": "Host(`a.example.com`) || Host(`b.example.com`)"}),
]


class FakeDocker:
    async def containers(self):
        return CONTAINERS


class FakeSSH:
    def __init__(self, answers):
        self.answers = answers

    async def run(self, cmd, timeout=15):
        return next((a for k, a in self.answers.items() if k in cmd), "")


def run(name, answers=None):
    return asyncio.run(suggest_module(name, FakeSSH(answers or {}), FakeDocker()))


def test_container_urls():
    qb, _, radarr, *_ = [Container(c) for c in CONTAINERS]
    assert qb.url(8080) == "http://127.0.0.1:8181" and qb.url(9999) is None
    assert radarr.url(7878) == "http://127.0.0.1:7878"
    assert qb.is_("qbittorrent") and not qb.is_("sonarr")
    assert app_root(qb) == "/srv/appdata"


def test_downloads():
    s = run("downloads", {"sonarr/config.xml": "<Config><ApiKey>0123456789abcdef0123456789abcdef</ApiKey></Config>"})
    assert s["qbittorrent_url"]["value"] == "http://127.0.0.1:8181"
    assert s["sonarr_url"]["value"] == "http://127.0.0.1:8989"
    assert s["sonarr_key"]["value"] == "0123456789abcdef0123456789abcdef"
    assert s["radarr_url"]["value"] == "http://127.0.0.1:7878" and "radarr_key" not in s


def test_sites_from_npm_and_traefik():
    s = run("sites", {"proxy_host": "https www.example.org\nhttps example.org\nhttp lan.example.org\n"})
    assert s["urls"]["value"] == ["https://a.example.com", "https://b.example.com", "https://example.org",
                                  "https://www.example.org", "http://lan.example.org"]


def test_backups_jellyfin_files_raid_claude():
    assert run("backups")["source"]["value"] == "/srv/appdata"
    j = run("jellyfin", {"test -s": "yes\n"})
    assert j["jellyfin_url"]["value"] == "http://127.0.0.1:8097"
    assert j["db"]["value"] == "/srv/appdata/jellyfin/config/data/jellyfin.db" and "jfa_url" not in j
    f = run("files", {"findmnt": "/\n/boot/efi\n/mnt/a\n/mnt/b\n/data\n/srv/media\n"})
    assert f["roots"]["value"] == ["~", "/data", "/mnt", "/srv/media"]
    assert run("raid", {"/proc/mdstat": "md0 : active raid1 sdb1[1] sda1[0]\n", "sudo": "yes\n"}) == {
        "device": {"value": "/dev/md0", "why": "el RAID activo de /proc/mdstat"},
        "sudo": {"value": True, "why": "tu usuario puede usar smartctl con sudo sin contraseña"}}
    assert run("raid", {"/proc/mdstat": "unused devices: <none>\n", "sudo": "yes\n"}) == {}
    assert run("claude", {"command -v": "/opt/claude/bin/claude\n/home/u\n"})["bin"]["value"] == "/opt/claude/bin/claude"
    assert run("claude", {"command -v": "/home/u/.local/bin/claude\n/home/u\n"}) == {}


def test_nothing_without_docker_or_ssh():
    class Broken:
        async def containers(self):
            raise OSError("no socket")

    assert asyncio.run(suggest_module("downloads", FakeSSH({}), Broken())) == {}
    assert asyncio.run(Env(FakeSSH({}), None).containers()) == []
    assert run("stocks") == {}  # sin suggest.py


def test_endpoint(tmp_path):
    c = client(tmp_path, "modules: {}\n")
    assert c.get("/api/modules/nope/suggest").status_code == 404
    assert c.get("/api/modules/stocks/suggest").json() == {}
    c.cookies.clear()
    assert c.get("/api/modules/stocks/suggest").status_code == 401
