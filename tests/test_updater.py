from app.modules.updates.updater import build_create_body, split_image

IMAGE = {"Id": "sha256:old", "Config": {
    "Env": ["PATH=/usr/bin", "VERSION=1.0", "PUID=911"],
    "Labels": {"org.opencontainers.image.version": "1.0"},
    "Cmd": ["/init"], "Entrypoint": None, "WorkingDir": "/app", "User": "",
    "ExposedPorts": {"8096/tcp": {}}, "Volumes": {"/config": {}}}}


def container(**over):
    c = {
        "Id": "abcdef1234567890", "Name": "/jellyfin", "Image": "sha256:old",
        "Config": {
            "Hostname": "abcdef123456", "Domainname": "", "Image": "linuxserver/jellyfin",
            "Env": ["PATH=/usr/bin", "VERSION=1.0", "PUID=1000", "TZ=Europe/Madrid"],
            "Labels": {"org.opencontainers.image.version": "1.0", "com.docker.compose.project": "jellyfin", "icon": "x"},
            "Cmd": ["/init"], "Entrypoint": None, "WorkingDir": "/app", "User": "",
            "ExposedPorts": {"8096/tcp": {}}, "Volumes": {"/config": {}}, "Tty": False,
        },
        "HostConfig": {"Binds": ["/srv/appdata/jellyfin/config:/config"], "NetworkMode": "bridge",
                       "RestartPolicy": {"Name": "unless-stopped"}},
        "Mounts": [
            {"Type": "bind", "Source": "/srv/appdata/jellyfin/config", "Destination": "/config"},
            {"Type": "volume", "Name": "f00dvol", "Destination": "/cache"},
        ],
        "NetworkSettings": {"Networks": {"bridge": {"Aliases": None, "IPAMConfig": None, "Links": None},
                                         "jellyfin_default": {"Aliases": ["jellyfin", "abcdef123456"], "IPAMConfig": None,
                                                              "Links": None, "MacAddress": "02:42:ac:11:00:02"}}},
    }
    c.update(over)
    return c


def test_strips_image_defaults_keeps_user_config():
    name, body = build_create_body(container(), IMAGE)
    assert name == "jellyfin"
    cfg = body
    assert cfg["Image"] == "linuxserver/jellyfin"
    assert cfg["Env"] == ["PUID=1000", "TZ=Europe/Madrid"]  # PATH y VERSION vienen de la imagen vieja
    assert cfg["Labels"] == {"com.docker.compose.project": "jellyfin", "icon": "x"}
    assert "Cmd" not in cfg and "WorkingDir" not in cfg and "ExposedPorts" not in cfg and "Volumes" not in cfg
    assert "Hostname" not in cfg  # era el id por defecto


def test_keeps_custom_cmd_and_hostname():
    c = container()
    c["Config"]["Cmd"] = ["--custom"]
    c["Config"]["Hostname"] = "adguard"
    _, cfg = build_create_body(c, IMAGE)
    assert cfg["Cmd"] == ["--custom"] and cfg["Hostname"] == "adguard"


def test_anonymous_volume_reused_and_binds_kept():
    _, cfg = build_create_body(container(), IMAGE)
    binds = cfg["HostConfig"]["Binds"]
    assert "/srv/appdata/jellyfin/config:/config" in binds
    assert "f00dvol:/cache" in binds


def test_networks():
    _, cfg = build_create_body(container(), IMAGE)
    eps = cfg["NetworkingConfig"]["EndpointsConfig"]
    assert set(eps) == {"bridge", "jellyfin_default"}
    assert eps["jellyfin_default"]["Aliases"] == ["jellyfin"]  # sin el id corto viejo
    assert "MacAddress" not in eps["jellyfin_default"]


def test_host_network_drops_hostname_and_endpoints():
    c = container()
    c["HostConfig"]["NetworkMode"] = "host"
    c["Config"]["Hostname"] = "myhost"
    c["NetworkSettings"]["Networks"] = {"host": {}}
    _, cfg = build_create_body(c, IMAGE)
    assert "Hostname" not in cfg and "NetworkingConfig" not in cfg


def test_split_image():
    assert split_image("linuxserver/jellyfin") == ("linuxserver/jellyfin", "latest")
    assert split_image("ghcr.io/hotio/qbittorrent:latest") == ("ghcr.io/hotio/qbittorrent", "latest")
    assert split_image("localhost:5000/x") == ("localhost:5000/x", "latest")


import asyncio  # noqa: E402

import pytest  # noqa: E402

from app.modules.updates import updater as U  # noqa: E402


class FakeDocker:
    def __init__(self, new_state):
        self.new_state = new_state
        self.calls = []
        self.containers_ = {"web": {"Id": "a" * 64, "Name": "/web", "Image": "sha256:old",
                                    "Config": {"Image": "nginx:alpine", "Hostname": "aaaaaaaaaaaa"},
                                    "HostConfig": {"NetworkMode": "bridge"}, "Mounts": [],
                                    "NetworkSettings": {"Networks": {"bridge": {}}}}}

    async def inspect_container(self, name):
        if name == "web" and ("create", "web") in self.calls:
            return {"State": self.new_state}
        return self.containers_["web"]

    async def inspect_image(self, ref):
        return {"Id": "sha256:new" if ref == "nginx:alpine" else "sha256:old", "Config": {}}

    async def pull(self, repo, tag, on_line=None):
        self.calls.append(("pull", f"{repo}:{tag}"))

    async def stop(self, n): self.calls.append(("stop", n))
    async def start(self, n): self.calls.append(("start", n))
    async def rename(self, n, new): self.calls.append(("rename", n, new))
    async def create(self, n, body): self.calls.append(("create", n)); return "id"
    async def remove(self, n): self.calls.append(("remove", n))


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(U, "WAIT_SECONDS", 1)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(U.asyncio, "sleep", lambda s: real_sleep(0))


async def run_job(d):
    up = U.Updater(d, http=None)
    j = up.start("web")
    while j.status == "running":
        await asyncio.sleep(0)
    return j


async def test_update_ok_removes_old():
    d = FakeDocker({"Running": True, "Health": {"Status": "healthy"}})
    j = await run_job(d)
    assert j.status == "ok", j.lines
    assert ("rename", "web", "web-pocketpanel-old") in d.calls
    assert d.calls[-1] == ("remove", "web-pocketpanel-old")


async def test_update_fails_and_rolls_back():
    d = FakeDocker({"Running": False, "Status": "exited", "ExitCode": 1})
    j = await run_job(d)
    assert j.status == "failed"
    tail = d.calls[-3:]
    assert tail == [("remove", "web"), ("rename", "web-pocketpanel-old", "web"), ("start", "web")]


async def test_noop_when_same_image():
    d = FakeDocker({})

    async def same(ref):
        return {"Id": "sha256:old", "Config": {}}
    d.inspect_image = same
    j = await run_job(d)
    assert j.status == "noop" and not any(c[0] == "stop" for c in d.calls)


def test_refuses_self_update():
    with pytest.raises(ValueError):
        U.Updater(FakeDocker({}), http=None).start("pocketpanel")


async def test_check_marks_updates(monkeypatch):
    import app.modules.updates.registry as R

    class D(FakeDocker):
        async def containers(self):
            return [{"Names": ["/web"], "Image": "nginx:alpine"}, {"Names": ["/mine"], "Image": "mine"},
                    {"Names": ["/pocketpanel"], "Image": "pocketpanel"}]

        async def inspect_image(self, ref):
            if ref == "mine":
                return {"Id": "x", "RepoDigests": []}
            return {"Id": "y", "RepoDigests": ["nginx@sha256:old"]}

    async def fake_remote(client, registry, repo, tag):
        assert (registry, repo, tag) == ("registry-1.docker.io", "library/nginx", "alpine")
        return "sha256:new"
    monkeypatch.setattr(R, "remote_digest", fake_remote)
    up = U.Updater(D({}), http=None)
    res = await up.check()
    assert res["web"]["status"] == "update" and res["mine"]["status"] == "local" and "pocketpanel" not in res
    assert up.checked_at


async def test_check_failure_still_sets_checked_at():
    class D(FakeDocker):
        async def containers(self):
            raise RuntimeError("docker caído")
    up = U.Updater(D({}), http=None)
    with pytest.raises(RuntimeError):
        await up.check()
    assert up.checked_at and not up.checking


async def test_results_persist(tmp_path):
    class D(FakeDocker):
        async def containers(self):
            return []
    up = U.Updater(D({}), http=None, data_dir=str(tmp_path))
    up.results = {"x": {"status": "update"}}
    await up.check()
    again = U.Updater(D({}), http=None, data_dir=str(tmp_path))
    assert again.checked_at == up.checked_at


async def test_update_all_one_backup_continues_after_failure():
    class Multi(FakeDocker):
        def __init__(self):
            super().__init__({})
            self.created = set()

        async def inspect_container(self, name):
            if name in self.created:
                ok = name != "bad"
                return {"State": {"Running": ok, "Status": "running" if ok else "exited", "ExitCode": 0 if ok else 1,
                                  "Health": {"Status": "healthy"} if ok else None}}
            c = dict(self.containers_["web"])
            c["Name"] = "/" + name
            return c

        async def create(self, n, body):
            self.created.add(n)
            self.calls.append(("create", n))
            return "id"

    class B:
        def __init__(self):
            self.labels = []

        async def run(self, label=""):
            self.labels.append(label)
            return {"ok": True, "snapshot": f"x-{label}"}

    d, b = Multi(), B()
    up = U.Updater(d, http=None, backup=b)
    up.results = {"good": {"status": "update"}, "bad": {"status": "update"}, "fine": {"status": "ok"},
                  "pocketpanel": {"status": "update"}}
    j = up.start_all()
    while j.status == "running":
        await asyncio.sleep(0)
    assert b.labels == ["antes-actualizar-todo"]  # un único backup
    assert j.status == "failed" and "fallaron (vueltos atrás): bad" in j.lines[-1]
    assert up.jobs["good"].status == "ok" and up.jobs["bad"].status == "failed"
    assert ("create", "fine") not in d.calls and ("create", "pocketpanel") not in d.calls


def test_update_all_nothing_to_do():
    up = U.Updater(FakeDocker({}), http=None)
    with pytest.raises(ValueError):
        up.start_all()
