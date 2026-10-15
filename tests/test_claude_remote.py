import json

from app.claude import ClaudePaths, SessionStore

SID = "7f0c498a-d4fb-4620-87f7-16553d8453f6"
SID2 = "11111111-1111-4111-8111-111111111111"


def session(text):
    return json.dumps({"type": "user", "message": {"content": text}}) + "\n" + json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hola"}]}}) + "\n"


class FS:
    def __init__(self, files):
        self.files, self.reads = files, []

    async def listdir(self, folder):
        if folder != "/h/.claude/projects/-srv":
            raise FileNotFoundError(folder)
        return [(n, m, len(t)) for n, (m, t) in self.files.items()]

    async def read_text(self, path):
        self.reads.append(path)
        name = path.rsplit("/", 1)[1]
        if name not in self.files:
            raise FileNotFoundError(path)
        return self.files[name][1]


async def folder():
    return "/h/.claude/projects/-srv"


async def test_list_sorted_cached_and_skips_empty():
    fs = FS({f"{SID}.jsonl": (100, session("viejo")), f"{SID2}.jsonl": (200, session("nuevo")),
             "x.jsonl": (300, ""), "notas.txt": (400, "x")})
    st = SessionStore(fs, folder)
    r = await st.list()
    assert [s["title"] for s in r] == ["nuevo", "viejo"] and r[0]["updated"] == 200
    n = len(fs.reads)
    await st.list()
    assert len(fs.reads) == n  # sin cambios: no se vuelve a leer


async def test_read_and_bad_ids():
    fs = FS({f"{SID}.jsonl": (100, session("hola claude"))})
    st = SessionStore(fs, folder)
    r = await st.read(SID)
    assert r["title"] == "hola claude" and r["messages"][0] == {"t": "user", "d": "hola claude"}
    assert await st.read("../../etc/passwd") is None
    assert await st.read(SID2) is None


async def test_missing_folder_is_empty():
    async def nowhere():
        return "/nope"
    assert await SessionStore(FS({}), nowhere).list() == []


class SSH:
    def __init__(self):
        self.calls = 0

    async def run(self, cmd, timeout=15):
        self.calls += 1
        return "/home/ramon"


async def test_paths_default_to_host_user_home():
    ssh = SSH()
    p = ClaudePaths(ssh, {"home": "", "cwd": "", "bin": ""}, env_home="", env_cwd="")
    r = await p.resolve()
    assert r == {"home": "/home/ramon", "cwd": "/home/ramon", "bin": "/home/ramon/.local/bin/claude",
                 "sessions": "/home/ramon/.claude/projects/-home-ramon"}
    await p.resolve()
    assert ssh.calls == 1


async def test_paths_from_config_win_over_env():
    p = ClaudePaths(SSH(), {"home": "/srv/claude", "cwd": "/srv/my.data", "bin": "/usr/bin/claude"},
                    env_home="/old", env_cwd="/old")
    r = await p.resolve()
    assert r["home"] == "/srv/claude" and r["bin"] == "/usr/bin/claude"
    assert r["sessions"] == "/srv/claude/.claude/projects/-srv-my-data"
    q = await ClaudePaths(SSH(), {"home": "", "cwd": "", "bin": ""}, env_home="/env", env_cwd="").resolve()
    assert q["home"] == "/env" and q["cwd"] == "/env"


async def test_sftp_errors_become_ssh_errors():
    import asyncssh
    import pytest

    from app.claude import SftpFS
    from app.ssh import SSHError

    class Conn:
        def start_sftp_client(self):
            raise asyncssh.ChannelOpenError(1, "subsystem request failed")

    class SSH:
        async def conn(self):
            return Conn()

    with pytest.raises(SSHError, match="SFTP"):
        await SftpFS(SSH()).listdir("/x")
