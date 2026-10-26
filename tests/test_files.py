import asyncio
import io
import os
import stat
import tarfile
import time

import pytest

from app.modules.files.files import Files, valid_name
from app.modules.files.fs import FilesError, NotFound


class LocalFS:
    """Lo mismo que SftpFS pero en el disco local (y los comandos, aquí): los cp/mv/rm/tar son de verdad."""

    def __init__(self, home):
        self.home = str(home)

    async def realpath(self, path):
        p = self.home if path == "." else path
        if not os.path.lexists(p):
            raise NotFound(f"no existe: {path}")
        return os.path.realpath(p)

    async def stat(self, path):
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return None
        return {"name": os.path.basename(path), "dir": stat.S_ISDIR(st.st_mode), "link": False, "size": st.st_size,
                "mtime": int(st.st_mtime)}

    async def listdir(self, path):
        out = []
        for n in os.listdir(path):
            p = os.path.join(path, n)
            st = os.stat(p) if os.path.exists(p) else os.lstat(p)
            out.append({"name": n, "dir": stat.S_ISDIR(st.st_mode), "link": os.path.islink(p), "size": st.st_size,
                        "mtime": int(st.st_mtime)})
        return out

    async def mkdir(self, path):
        os.mkdir(path)

    async def rename(self, old, new):
        if os.path.lexists(new):
            raise FilesError("ya existe")
        os.rename(old, new)

    async def remove(self, path):
        os.remove(path)

    async def free(self, path):
        v = os.statvfs(path)
        return {"free": v.f_bavail * v.f_frsize, "total": v.f_blocks * v.f_frsize}

    async def read(self, path, start=0, end=None):
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read() if end is None else f.read(end - start)
        for i in range(0, len(data), 4):
            yield data[i:i + 4]

    async def write(self, path, chunks):
        n = 0
        with open(path, "wb") as f:
            async for c in chunks:
                f.write(c)
                n += len(c)
        return n

    async def run(self, cmd):
        p = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await p.communicate()
        return p.returncode, err.decode().strip()

    async def stream(self, cmd):
        p = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE)
        while data := await p.stdout.read(65536):
            yield data
        await p.wait()


@pytest.fixture
def tree(tmp_path):
    home, mnt, secret = tmp_path / "home", tmp_path / "mnt", tmp_path / "secret"
    for d in (home / "docs", mnt / "media", secret):
        d.mkdir(parents=True)
    (home / "docs" / "a.txt").write_text("hola\n")
    (home / "docs" / "b.tar.gz").write_bytes(b"x" * 10)
    (home / ".oculto").write_text("")
    (mnt / "media" / "peli.mkv").write_bytes(b"0123456789")
    (secret / "clave").write_text("no")
    os.symlink(secret, home / "atajo")  # un enlace que sale de las carpetas permitidas
    return tmp_path


def files(tree):
    return Files(LocalFS(tree / "home"), ["~", str(tree / "mnt"), str(tree / "no-existe")])


async def wait(f, j):
    while f.jobs[j["job"]].status == "running":
        await asyncio.sleep(0.01)
    return f.jobs[j["job"]]


def run(coro):
    return asyncio.run(coro)


def test_roots_and_listing(tree):
    f = files(tree)
    roots = run(f.roots())
    assert [r["path"] for r in roots] == [str(tree / "home"), str(tree / "mnt")]  # la que no existe no sale
    assert roots[0]["name"] == "Inicio"
    d = run(f.listing(str(tree / "home")))
    assert [e["name"] for e in d["items"]][:2] == ["atajo", "docs"]  # carpetas primero
    assert d["parent"] is None and d["root"] == str(tree / "home")
    sub = run(f.listing(str(tree / "home" / "docs") + "/"))
    assert sub["parent"] == str(tree / "home") and sub["free"]["total"] > 0


def test_paths_stay_inside_roots(tree):
    f = files(tree)
    for bad in [str(tree / "secret"), str(tree / "home" / ".." / "secret"), str(tree / "home" / "atajo"),
                "relativa", str(tree / "home" / "atajo" / "clave")]:
        with pytest.raises(FilesError):
            run(f.listing(bad))
    with pytest.raises(FilesError):
        run(f.read_text(str(tree / "home" / "atajo" / "clave")))


def test_names():
    for bad in ["", "..", ".", "a/b", "x\0", "a" * 256]:
        with pytest.raises(FilesError):
            valid_name(bad)
    assert valid_name("Fotos 2026") == "Fotos 2026"


def test_copy_twice_and_move(tree):
    async def go():
        f = files(tree)
        docs, media = str(tree / "home" / "docs"), str(tree / "mnt" / "media")
        await wait(f, await f.paste([f"{docs}/a.txt", f"{docs}/b.tar.gz"], docs, move=False))
        await wait(f, await f.paste([f"{docs}/a.txt"], docs, move=False))
        names = sorted(os.listdir(docs))
        assert names == ["a (copia 2).txt", "a (copia).txt", "a.txt", "b (copia).tar.gz", "b.tar.gz"]
        job = await wait(f, await f.paste([docs], media, move=True))  # entre «discos»: mv
        assert job.status == "ok"
        assert not os.path.exists(docs) and os.path.isfile(f"{media}/docs/a (copia).txt")
        # lo que ya está en el destino no se mueve; lo que se llama igual no se pisa
        (tree / "home" / "docs").mkdir()
        await wait(f, await f.paste([str(tree / "home" / "docs")], media, move=True))
        assert sorted(os.listdir(media)) == ["docs", "docs (2)", "peli.mkv"]
        with pytest.raises(FilesError, match="dentro de sí misma"):
            await f.paste([media], f"{media}/docs", move=False)
        with pytest.raises(FilesError, match="carpeta de inicio"):
            await f.delete([str(tree / "mnt")])
    run(go())


def test_links_are_handled_as_links(tree):
    async def go():
        f = files(tree)
        home = tree / "home"
        os.symlink(home / "docs", home / "enlace")
        await wait(f, await f.paste([str(home / "enlace")], str(tree / "mnt"), move=False))
        assert os.path.islink(tree / "mnt" / "enlace")  # se copia el enlace, no la carpeta entera
        await f.rename(str(home / "enlace"), "enlace2")
        assert os.path.islink(home / "enlace2") and os.path.isdir(home / "docs")
        await wait(f, await f.delete([str(home / "enlace2"), str(home / "atajo")]))  # atajo apunta fuera: se borra él
        assert not os.path.lexists(home / "enlace2") and not os.path.lexists(home / "atajo")
        assert os.path.isfile(home / "docs" / "a.txt") and os.path.isfile(tree / "secret" / "clave")
        assert [e["name"] for e in (await f.listing(str(tree / "mnt" / "enlace")))["items"]][0] == "a.txt"
    run(go())


def test_delete_and_busy(tree):
    async def go():
        f = files(tree)
        j = await f.delete([str(tree / "mnt" / "media")])
        assert f.busy()
        job = await wait(f, j)
        assert job.status == "ok" and not f.busy()
        assert os.listdir(tree / "mnt") == []
        assert f.job(j["job"])["status"] == "ok"
    run(go())


def test_failed_job_reports(tree):
    async def go():
        f = files(tree)
        target = tree / "mnt" / "media"
        os.chmod(target, 0o500)  # sin escritura: cp falla
        try:
            job = await wait(f, await f.paste([str(tree / "home" / "docs" / "a.txt")], str(target), move=False))
        finally:
            os.chmod(target, 0o700)
        assert job.status == "failed" and job.lines[-1].split("  ", 1)[1].startswith("✗")
    if os.geteuid() == 0:
        pytest.skip("root escribe igual")
    run(go())


def test_new_rename_text_upload(tree):
    async def go():
        f = files(tree)
        home = str(tree / "home")
        await f.new(home, "nueva", True)
        await f.new(home, "nota.md", False)
        with pytest.raises(FilesError, match="ya existe"):
            await f.new(home, "nota.md", False)
        r = await f.rename(f"{home}/nota.md", "notas.md")
        assert r["path"] == f"{home}/notas.md"
        with pytest.raises(FilesError, match="ya existe"):
            await f.rename(f"{home}/notas.md", "docs")
        t = await f.read_text(f"{home}/notas.md")
        w = await f.write_text(f"{home}/notas.md", "# hola\n", t["mtime"])
        assert (tree / "home" / "notas.md").read_text() == "# hola\n"
        os.utime(tree / "home" / "notas.md", (1, 1))
        with pytest.raises(FilesError, match="ha cambiado"):
            await f.write_text(f"{home}/notas.md", "otra", w["mtime"])

        async def body():
            yield b"abc"
            yield b"def"
        up = await f.upload(home, "notas.md", body())  # no pisa: «notas (2).md»
        assert up == {"path": f"{home}/notas (2).md", "size": 6}
        assert not [n for n in os.listdir(home) if n.endswith(".parte")]
        (tree / "home" / "bin").write_bytes(b"\x00\x01")
        with pytest.raises(FilesError, match="no parece"):
            await f.read_text(f"{home}/bin")
    run(go())


def test_upload_cut_leaves_nothing(tree):
    async def go():
        f = files(tree)

        async def broken():
            yield b"abc"
            raise ConnectionError("se cortó")
        with pytest.raises(ConnectionError):
            await f.upload(str(tree / "home"), "x.bin", broken())
        assert not [n for n in os.listdir(tree / "home") if "x.bin" in n]
    run(go())


@pytest.fixture
def api(tree, monkeypatch):
    from app.modules.files import api as files_api
    monkeypatch.setattr(files_api, "SftpFS", lambda ssh: LocalFS(tree / "home"))
    from tests.test_modules import client
    yml = f"modules:\n  files:\n    enabled: true\n    roots: ['~', '{tree / 'mnt'}']\n"
    (tree / "app").mkdir()
    with client(tree / "app", yml) as c:  # con el bucle vivo entre peticiones: la copia va en segundo plano
        yield c


def test_api(api, tree):
    home = str(tree / "home")
    assert api.get("/api/files/roots").json()["roots"][0]["path"] == home
    assert api.get("/api/files/list", params={"path": str(tree / "secret")}).status_code == 400
    assert api.get("/api/files/list", params={"path": f"{home}/nada"}).status_code == 404
    r = api.put("/api/files/upload", params={"path": home, "name": "foto.png"}, content=b"\x89PNG....")
    assert r.status_code == 200
    # descarga normal, por trozos (vídeo) y en línea solo si es seguro
    d = api.get("/api/files/download", params={"path": f"{home}/foto.png", "inline": 1})
    assert d.content == b"\x89PNG...." and d.headers["content-type"] == "image/png"
    assert d.headers["content-disposition"].startswith("inline") and d.headers["content-security-policy"] == "sandbox"
    (tree / "home" / "x.html").write_text("<script>alert(1)</script>")
    h = api.get("/api/files/download", params={"path": f"{home}/x.html", "inline": 1})
    assert h.headers["content-type"] == "application/octet-stream" and h.headers["content-disposition"].startswith("attachment")
    mkv = str(tree / "mnt" / "media" / "peli.mkv")
    part = api.get("/api/files/download", params={"path": mkv}, headers={"Range": "bytes=2-5"})
    assert part.status_code == 206 and part.content == b"2345" and part.headers["content-range"] == "bytes 2-5/10"
    assert api.get("/api/files/download", params={"path": mkv}, headers={"Range": "bytes=-3"}).content == b"789"
    assert api.get("/api/files/download", params={"path": mkv}, headers={"Range": "bytes=20-"}).status_code == 416
    # una carpeta baja como .tar
    t = api.get("/api/files/download", params={"path": f"{home}/docs"})
    assert t.headers["content-type"] == "application/x-tar" and 'docs.tar' in t.headers["content-disposition"]
    assert sorted(tarfile.open(fileobj=io.BytesIO(t.content)).getnames()) == ["docs", "docs/a.txt", "docs/b.tar.gz"]
    # copiar y seguir la tarea
    j = api.post("/api/files/paste", json={"sources": [f"{home}/docs/a.txt"], "dest": str(tree / "mnt"), "move": False}).json()
    for _ in range(200):
        v = api.get(f"/api/files/jobs/{j['job']}").json()
        if v["status"] != "running":
            break
        time.sleep(0.02)
    assert v["status"] == "ok" and (tree / "mnt" / "a.txt").read_text() == "hola\n"
    assert api.get("/api/files/jobs/999").status_code == 404
    assert api.post("/api/files/rename", json={"path": f"{home}/foto.png", "name": "../x"}).status_code == 400


def test_api_needs_login(tree, monkeypatch):
    from app.modules.files import api as files_api
    monkeypatch.setattr(files_api, "SftpFS", lambda ssh: LocalFS(tree / "home"))
    from tests.test_modules import client
    (tree / "app").mkdir()
    c = client(tree / "app", "modules:\n  files:\n    enabled: true\n")
    c.cookies.clear()
    assert c.get("/api/files/list", params={"path": str(tree / "home")}).status_code == 401
    assert c.get("/api/files/download", params={"path": str(tree / "home" / ".oculto")}).status_code == 401
