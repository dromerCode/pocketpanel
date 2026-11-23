"""Módulo clientes: lo que imprime panel.sh → datos, y la comprobación de lo que se le pide."""
import pytest

from app.modules.clientes.clientes import (ClientesError, build_action, human_schedule, parse_copias, parse_crons,
                                           parse_dns, parse_estado, parse_job, parse_sucesos, sections)

ESTADO = """@@modo
vm|
@@vigilancia
fallos|1
parcial|no
ahora|1794409977
ips|203.0.113.7|203.0.113.8
@@proyectos
tienda|yo/tienda|docker|8088|si|/login|tienda.example.com www.tienda.example.com|26d4e57||1793971313|1793968241|Arregla a|b
blog|yo/blog|web|8086|no|/|blog.example.com|c8727e9|abc1234|1793969183|1791216169|Hola
@@copia
fecha|2026-11-11 02:00:19
@@trabajo
idle|Copia de seguridad|1
@@casa-docker
tienda|exited|Exited (0) 5 days ago
@@publico
tienda|200|0.170339
blog|000|
@@vm-sys
443171.71 436766.34
0.16 0.09 0.09 3/373 205632
2
MemTotal:        4000000 kB
MemAvailable:    3000000 kB
/dev/sda1      1000 250 750      25% /
@@vm-docker
tienda|running|Up 13 hours
blog|exited|Exited (1) 2 minutes ago
@@vm-http
tienda|200
blog|000
"""


def test_sections_repeat():
    assert sections("@@a\nx\n\n@@b\n@@a\ny") == [("a", ["x"]), ("b", []), ("a", ["y"])]


def test_estado():
    e = parse_estado(ESTADO)
    assert e["mode"] == "vm" and e["vigil"]["fails"] == 1 and e["vm"]["ok"]
    assert e["vm"]["cpus"] == 2 and e["vm"]["mem_used"] == 1000000 * 1024 and e["vm"]["disk_used"] == 250
    t, b = e["projects"]
    assert t["ok"] and t["data"] and t["domains"] == ["tienda.example.com", "www.tienda.example.com"]
    assert t["commit_msg"] == "Arregla a|b" and t["time_public"] == 0.17
    assert not b["ok"] and b["failed"] == "abc1234" and not b["running"]
    assert e["level"] == "bad" and any("blog no responde" in p for p in e["problems"])
    assert e["job"] == {"running": False, "name": "Copia de seguridad", "failed": True}


def test_estado_vm_caida_y_en_casa():
    out = ESTADO.split("@@vm-sys")[0].replace("vm|\n@@vigilancia", "casa|2026-11-10 10:00:00\n@@vigilancia") + "@@vm-error\n"
    e = parse_estado(out)
    assert e["mode"] == "casa" and not e["vm"]["ok"] and e["since"] == "2026-11-10 10:00:00"
    assert not e["projects"][0]["running"]  # en casa manda el contenedor de casa, que está parado


def test_dns():
    recs = ('{"result":[{"name":"tienda.example.com","type":"A","content":"203.0.113.7","proxied":true},'
            '{"name":"www.tienda.example.com","type":"A","content":"198.51.100.1","proxied":true},'
            '{"name":"nube.example.com","type":"A","content":"198.51.100.9","proxied":true},'
            '{"name":"_failover.example.com","type":"TXT","content":"\\"on\\""},'
            '{"name":"example.com","type":"MX","content":"mx"}]}')
    d = parse_dns("@@modo\nvm\n@@ip-casa\n198.51.100.9\n@@ip-vm\n203.0.113.7\n@@casa\nnube.example.com\n@@clientes\n"
                  "tienda.example.com|tienda\nwww.tienda.example.com|tienda\nfalta.example.com|tienda\n"
                  f"@@zona\nexample.com\n@@registros\n{recs}\n@@ns\nactive|a.ns b.ns\n")
    by = {r["name"]: r for r in d["records"]}
    assert by["tienda.example.com"]["ok"] and d["flag"] and not d["ok"]
    assert "203.0.113.7" in by["www.tienda.example.com"]["why"]
    assert "gris" in by["nube.example.com"]["why"] and by["falta.example.com"]["why"] == "no existe"
    assert d["zones"] == [{"name": "example.com", "status": "active", "ns": ["a.ns", "b.ns"], "others": 1}]


def test_copias():
    snaps = ('[{"time":"2026-11-10T01:00:18.1Z","tags":["vm"],"short_id":"aaaaaaaa","summary":{"total_bytes_processed":10}},'
             '{"time":"2026-11-11T01:00:19.057845413Z","tags":["casa"],"short_id":"bbbbbbbb"}]')
    c = parse_copias(f"@@fecha\n2026-11-11 02:00:19\n@@tam\n100\n200\n@@disco\n/dev/x 1000 600 400 60% /mnt\n"
                     f"@@datos\ntienda|50\n@@condatos\ntienda\n@@comprobado\n0\n@@snapshots\n{snaps}\n")
    assert [s["id"] for s in c["snapshots"]] == ["bbbbbbbb", "aaaaaaaa"] and c["snapshots"][0]["tag"] == "casa"
    assert c["size"] == 100 and c["repo_size"] == 200 and c["disk"]["free"] == 400 and c["checked_at"] is None
    assert parse_copias("@@snapshots\nno es json\n")["error"]


def test_sucesos_y_crons():
    ev = parse_sucesos("[2026-11-08 06:35:02] VM no responde (1/3): 'sin conexión'\n"
                       "[2026-11-08 06:35:02] AVISO: ❌ ERROR en la copia\n suelta\n[2026-11-09 02:00:20] Copia: OK (316K)\n")
    assert [e["level"] for e in ev] == ["ok", "bad", "warn"] and ev[1]["pushed"] and ev[1]["more"] == ["suelta"]
    assert human_schedule("*/5 * * * *".split()) == ("cada 5 min", None)
    assert human_schedule("30 2 * * *".split()) == ("cada día a las 02:30", "02:30")
    assert human_schedule("0 2 * * 1".split()) == ("0 2 * * 1", None)
    c = parse_crons("@@crons\n#PAUSADO# */5 * * * * $HOME/bin/clientes/vigilar-vm.sh >/dev/null\n"
                    "0 2 * * * $HOME/bin/clientes/copia-vm.sh && x\n@@latidos\nvigilancia|100\ncopia|90\n"
                    "despliegue|95|2\nerrores|0|0\nahora|200\n")
    by = {x["id"]: x for x in c["crons"]}
    assert by["vigilancia"]["paused"] and by["vigilancia"]["schedule"] == "cada 5 min" and by["vigilancia"]["last"] == 100
    assert by["noche"]["time"] == "02:00" and by["noche"]["deploy"] == {"at": 95, "errors": 2}
    assert not by["ddns"]["present"]


def test_job():
    assert parse_job("@none\n") is None
    assert parse_job("@running|Copia\nuno\n")["status"] == "running"
    assert parse_job("@done|Copia\nuno\n\n@rc 0\n") == {"status": "ok", "name": "Copia", "lines": ["uno"]}
    assert parse_job("@done|Copia\nuno\n@rc 1\n")["status"] == "failed"
    assert parse_job("@done|Copia\nuno\n")["lines"][-1] == "(se cortó antes de terminar)"


def test_build_action():
    assert build_action({"action": "copiar"}) == ["copiar"]
    assert build_action({"action": "desplegar"}) == ["desplegar"]
    assert build_action({"action": "reiniciar", "name": "proxy"}) == ["reiniciar", "proxy"]
    assert build_action({"action": "a-casa", "confirm": "casa"}) == ["a-casa"]
    assert build_action({"action": "restaurar", "name": "tienda", "snapshot": "31b4df7f", "confirm": "tienda"}) == [
        "restaurar", "tienda", "31b4df7f"]
    assert build_action({"action": "nuevo", "name": "tienda", "repo": "yo/tienda", "type": "web", "port": "8084",
                         "data": True, "domains": ["Tienda.example.com", "www.tienda.example.com"]}) == [
        "nuevo", "tienda", "yo/tienda", "web", "8084", "si", "/", "tienda.example.com www.tienda.example.com"]
    assert build_action({"action": "editar", "name": "tienda", "port": 8084, "path": "/login",
                         "domains": "a.example.com b.example.com"})[-1] == "a.example.com b.example.com"


@pytest.mark.parametrize("body", [
    {"action": "rm -rf /"}, {"action": "a-casa"}, {"action": "a-la-vm", "confirm": "casa"},
    {"action": "quitar", "name": "tienda"}, {"action": "quitar", "name": "tienda", "confirm": "otra"},
    {"action": "reiniciar", "name": "a; id"}, {"action": "desplegar", "name": "$(id)"},
    {"action": "restaurar", "name": "tienda", "snapshot": "latest; id", "confirm": "tienda"},
    {"action": "editar", "name": "tienda", "port": 80, "path": "/", "domains": ["a.example.com"]},
    {"action": "editar", "name": "tienda", "port": 8084, "path": "x", "domains": ["a.example.com"]},
    {"action": "editar", "name": "tienda", "port": 8084, "path": "/", "domains": ["a.example.com; id"]},
    {"action": "editar", "name": "tienda", "port": 8084, "path": "/", "domains": []},
    {"action": "nuevo", "name": "Tienda", "repo": "yo/tienda", "type": "web", "port": 8084, "domains": ["a.example.com"]},
    {"action": "nuevo", "name": "tienda", "repo": "https://x/y z", "type": "web", "port": 8084, "domains": ["a.example.com"]},
    {"action": "nuevo", "name": "tienda", "repo": "yo/tienda", "type": "php", "port": 8084, "domains": ["a.example.com"]},
])
def test_build_action_rejects(body):
    with pytest.raises(ClientesError):
        build_action(body)


def test_odd_output_does_not_break_the_screen():
    est = parse_estado("@@modo\nvm|\n@@vm-sys\nx\nnan? 1\n2\nMemTotal 5\nraro\n/dev\n@@publico\nweb|200|lento\n"
                       "@@proyectos\nweb|u/r|web|8080|no|/|a.example.com|abc||0|0|m\n")
    assert est["vm"]["ok"] and est["vm"]["load"] == [0.0, 1.0]
    assert est["projects"][0]["time_public"] is None
    cop = parse_copias('@@snapshots\n[{"time": "x"}, {"short_id": "ab"}, '
                       '{"time": "2026-11-11T02:00:19.1Z", "short_id": "cd", "tags": ["noche"]}]\n')
    assert [s["id"] for s in cop["snapshots"]] == ["cd"] and not cop["error"]
    dns = parse_dns('@@modo\nvm\n@@ip-vm\n1.2.3.4\n@@clientes\na.example.com|web\n@@zona\nexample.com\n'
                    '@@registros\n{"result": [{"id": 1}, {"type": "A", "name": "a.example.com", "content": "1.2.3.4"}]}\n')
    assert dns["records"][0]["why"] == "debería ir por Cloudflare (nube naranja)"


# ---------------------------------------------------------------- pruebas (en desarrollo)
PRUEBAS_OUT = """@@npm
no
@@copia
2026-11-19 02:00:17

@@produccion
agenda|usuario/agenda|docker|si|/login|8088
miweb|usuario/miweb-web|web|no|/|8085
@@pruebas
agenda|usuario/agenda|docker|9088|revisiones-cliente|agenda-test.example.org|si|/login|running|Up 3 minutes|200|1111111|si|copia de producción del 2026-11-19|abc1234|1763500000|Arreglo | con barra
nuevo|usuario/nuevo|web|9080|main|nuevo.example.org|no|/|exited|Exited (0)||?|no||def5678|1763400000|Primero
"""


def test_parse_pruebas():
    from app.modules.clientes.clientes import parse_pruebas
    d = parse_pruebas(PRUEBAS_OUT)
    assert d["npm"] is False and d["backup_at"]
    assert [p["name"] for p in d["production"]] == ["agenda", "miweb"]
    a, b = d["items"]
    assert a["ok"] and a["running"] and a["behind"] and a["in_prod"] and a["commit_msg"] == "Arreglo | con barra"
    assert a["branch"] == "revisiones-cliente" and a["port"] == 9088
    assert not b["running"] and not b["ok"] and b["remote"] is None and not b["behind"] and not b["in_prod"]


def test_build_action_pruebas():
    import pytest
    from app.modules.clientes.clientes import ClientesError, build_action
    assert build_action({"action": "prueba-crear", "name": "agenda", "port": 9088, "branch": "feature/x",
                         "domain": "agenda-test.example.org", "path": "/login", "mode": "copia"}) == \
        ["prueba-crear", "agenda", "-", "web", "9088", "feature/x", "agenda-test.example.org", "no", "/login", "copia"]
    assert build_action({"action": "prueba-actualizar", "name": "gacha", "branch": "main"}) == ["prueba-actualizar", "gacha", "main"]
    assert build_action({"action": "prueba-datos", "name": "gacha", "mode": "vacios", "confirm": "gacha"}) == ["prueba-datos", "gacha", "vacios"]
    for bad in ({"action": "prueba-actualizar", "name": "gacha", "branch": "--upload-pack=x"},
                {"action": "prueba-actualizar", "name": "gacha", "branch": "a/../b"},
                {"action": "prueba-crear", "name": "x1", "port": 9000, "branch": "main", "domain": "a.com b.com"},
                {"action": "prueba-quitar", "name": "gacha", "confirm": "otro"},
                {"action": "prueba-datos", "name": "gacha", "mode": "todo", "confirm": "gacha"}):
        with pytest.raises(ClientesError):
            build_action(bad)


# ---------------------------------------------------------------- credenciales de Nginx Proxy Manager
def test_npm_cred_input():
    import pytest
    from app.modules.clientes.clientes import ClientesError, npm_cred_input
    assert npm_cred_input(" yo@example.com ", "a b|c'$x") == ("yo@example.com", "a b|c'$x")
    for email, password in (("no-es-correo", "x"), ("yo@example.com", ""), ("yo@example.com", "a\nb"),
                            ("yo@example.com", None), (None, "x"), ("a b@example.com", "x")):
        with pytest.raises(ClientesError):
            npm_cred_input(email, password)


async def test_npm_cred_goes_by_stdin_not_in_the_command():
    import pytest
    from app.modules.clientes.clientes import Clientes, ClientesError

    class FakeSSH:
        def __init__(self, out):
            self.out, self.calls = out, []

        async def run(self, cmd, timeout=15, input=None):
            self.calls.append((cmd, input))
            return self.out

    ssh = FakeSSH("ok\n")
    await Clientes(ssh, "~/bin/clientes/panel.sh").npm_cred("yo@example.com", "s3creta")
    cmd, stdin = ssh.calls[0]
    assert cmd.endswith("npm-cred") and "s3creta" not in cmd and stdin == "yo@example.com\ns3creta\n"
    with pytest.raises(ClientesError, match="no acepta"):
        await Clientes(FakeSSH("Nginx Proxy Manager no acepta ese correo y contraseña\n"),
                       "~/bin/clientes/panel.sh").npm_cred("yo@example.com", "mala")


# ---------------------------------------------------------------- revisión: nada fijo del servidor de su autor
class _SSH:
    def __init__(self, out):
        self.out = out

    async def run(self, cmd, timeout=15, input=None):
        return self.out


async def test_pruebas_lleva_el_dominio_de_las_pruebas_de_la_config():
    from app.modules.clientes.clientes import Clientes
    d = await Clientes(_SSH(PRUEBAS_OUT), "~/bin/clientes/panel.sh", test_domain="Pruebas.Example.org").pruebas()
    assert d["test_domain"] == "pruebas.example.org"
    d = await Clientes(_SSH(PRUEBAS_OUT), "~/bin/clientes/panel.sh").pruebas()
    assert d["test_domain"] == ""


def test_dominio_de_pruebas_no_valido():
    from app.modules.clientes.clientes import Clientes
    for bad in ("no dominio", "-x.com", "a.com;id"):
        with pytest.raises(ClientesError):
            Clientes(_SSH(""), "~/bin/clientes/panel.sh", test_domain=bad)


async def test_ramas_no_ofrece_las_que_no_se_podrian_usar():
    from app.modules.clientes.clientes import Clientes
    out = "main\n-mala\nfeat/a..b\n/raiz\nfeat/pago\n"
    assert await Clientes(_SSH(out), "~/bin/clientes/panel.sh").ramas("demo/tienda") == ["main", "feat/pago"]


@pytest.mark.parametrize("repo", ["../x", "./x", "a/..", "a/.", "-a/b"])
def test_repo_no_valido(repo):
    with pytest.raises(ClientesError):
        build_action({"action": "nuevo", "name": "tienda", "repo": repo, "type": "web", "port": 9000,
                      "domains": "tienda.example.com"})
