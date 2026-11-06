import json
import stat

import httpx
import pytest

from app.modules.ntfy.ntfy import Ntfy, NtfyError, parse, topic_of


def line(id, t, topic="a", **kw):
    return json.dumps({"id": id, "time": t, "event": "message", "topic": topic, "message": f"m{id}", **kw})


class Fake:
    """Un ntfy de mentira: responde con los mensajes cuyo time >= since y apunta lo que le piden."""

    def __init__(self, msgs=(), status=200):
        self.msgs, self.status, self.calls = list(msgs), status, []

    def __call__(self, req: httpx.Request):
        topics = req.url.path.split("/")[1].split(",")
        since = req.url.params["since"]
        self.calls.append((topics, since, req.headers.get("authorization")))
        if self.status != 200:
            return httpx.Response(self.status, json={"code": 1, "error": "nope"})
        out = [m for m in self.msgs if json.loads(m)["topic"] in topics
               and (since == "all" or json.loads(m)["time"] >= int(since))]
        return httpx.Response(200, text="\n".join(out) + "\n")


def make(tmp_path, fake, clock, token=""):
    return Ntfy(str(tmp_path), "https://ntfy.example/", token, http=httpx.AsyncClient(transport=httpx.MockTransport(fake)),
                now=lambda: clock[0])


def test_topic_of():
    assert topic_of("mi-tema_1") == "mi-tema_1"
    assert topic_of(" https://ntfy.sh/mi-tema/ ") == "mi-tema"
    assert topic_of("ntfy.sh/abc") == "abc"
    for bad in ("", "con espacio", "a" * 65, "tema,otro", "ñ"):
        with pytest.raises(NtfyError):
            topic_of(bad)


def test_parse_keeps_messages_only_and_safe_links():
    text = "\n".join([
        json.dumps({"id": "k", "time": 1, "event": "keepalive", "topic": "a"}),
        "basura",
        line("1", 5, title="T", priority=5, tags=["warning", "x1"], click="javascript:alert(1)",
             attachment={"name": "f.png", "url": "https://x/f.png"}),
        line("2", 6, click="https://ok"),
    ])
    a, b = parse(text)
    assert (a["id"], a["title"], a["priority"], a["tags"], a["click"]) == ("1", "T", 5, ["warning", "x1"], "")
    assert a["attachment"] == {"name": "f.png", "url": "https://x/f.png"}
    assert (b["priority"], b["click"], b["attachment"]) == (3, "https://ok", None)


async def test_subscribe_backfills_quietly_then_reports_new(tmp_path):
    fake, clock = Fake([line("1", 100), line("2", 200)]), [1000]
    nt = make(tmp_path, fake, clock, token="tk_x")
    assert await nt.poll() == []                       # sin temas no pregunta
    assert fake.calls == []
    await nt.add("https://ntfy.sh/a")
    assert await nt.poll() == []                       # lo que ya había se guarda, pero no es «nuevo»
    assert [m["id"] for m in nt.view()["messages"]] == ["2", "1"]
    assert fake.calls[-1] == (["a"], "all", "Bearer tk_x")

    fake.msgs.append(line("3", 1005))
    clock[0] = 1030
    assert [m["id"] for m in await nt.poll()] == ["3"]
    assert fake.calls[-1][1] == str(1000 - 60)         # desde el último vistazo, con margen
    clock[0] = 1035
    assert await nt.poll(max_age=10) == []             # recién mirado: no vuelve a preguntar
    assert len(fake.calls) == 2
    assert await nt.poll() == []                       # lo repetido por el margen no cuenta dos veces
    assert [m["id"] for m in nt.view()["messages"]] == ["3", "2", "1"]


async def test_new_topic_backfills_only_itself(tmp_path):
    fake, clock = Fake([line("1", 100, "a"), line("2", 100, "b")]), [1000]
    nt = make(tmp_path, fake, clock)
    await nt.add("a")
    await nt.poll()
    fake.msgs.append(line("3", 1001, "a"))
    await nt.add("b")
    clock[0] = 1010
    new = await nt.poll()
    assert fake.calls[-1][:2] == (["a", "b"], "all")
    assert [m["id"] for m in new] == ["3"]             # «2» era de antes de suscribirse a b
    assert {m["id"] for m in nt.view()["messages"]} == {"1", "2", "3"}


async def test_state_survives_restart_and_is_private(tmp_path):
    fake, clock = Fake([line("1", 100)]), [1000]
    nt = make(tmp_path, fake, clock)
    await nt.add("a")
    await nt.poll()
    assert stat.S_IMODE((tmp_path / "ntfy.json").stat().st_mode) == 0o600
    again = make(tmp_path, fake, clock)
    assert again.view()["topics"] == ["a"] and len(again.view()["messages"]) == 1
    await again.poll()
    assert fake.calls[-1][1] == str(1000 - 60)


async def test_remove_drops_its_messages(tmp_path):
    fake, clock = Fake([line("1", 100, "a"), line("2", 100, "b")]), [1000]
    nt = make(tmp_path, fake, clock)
    await nt.add("a")
    await nt.add("b")
    await nt.poll()
    await nt.remove("a")
    v = nt.view()
    assert v["topics"] == ["b"] and [m["id"] for m in v["messages"]] == ["2"]


async def test_errors_are_shown_not_raised(tmp_path):
    clock = [1000]
    nt = make(tmp_path, Fake(status=403), clock)
    await nt.add("a")
    assert await nt.poll() == []
    assert "token" in nt.view()["error"]

    def down(req):
        raise httpx.ConnectError("sin red")
    nt2 = make(tmp_path / "x", down, clock)
    await nt2.add("a")
    await nt2.poll()
    assert "sin red" in nt2.view()["error"]


async def test_keeps_the_latest_per_topic(tmp_path, monkeypatch):
    monkeypatch.setattr("app.modules.ntfy.ntfy.KEEP", 3)
    fake, clock = Fake([line(str(i), i, "a") for i in range(10)] + [line("b1", 1, "b")]), [1000]
    nt = make(tmp_path, fake, clock)
    await nt.add("a")
    await nt.add("b")
    await nt.poll()
    assert [m["id"] for m in nt.view()["messages"]] == ["9", "8", "7", "b1"]


def test_parse_survives_odd_fields():
    """Un mensaje raro de un servidor ajeno no tira la lectura de todos los demás."""
    a, b = parse("\n".join([line("1", "ayer", tags=5), line("2", 6)]))
    assert (a["id"], a["time"], a["tags"]) == ("1", 0, [])
    assert b["id"] == "2"


async def test_new_topic_doesnt_report_old_messages_already_trimmed(tmp_path, monkeypatch):
    """Al suscribirse a otro tema se pide «all»: lo viejo que ya se recortó de los demás no es nuevo."""
    monkeypatch.setattr("app.modules.ntfy.ntfy.KEEP", 3)
    fake, clock = Fake([line(str(i), i, "a") for i in range(10)]), [1000]
    nt = make(tmp_path, fake, clock)
    await nt.add("a")
    await nt.poll()
    await nt.add("b")
    clock[0] = 1010
    assert await nt.poll() == []
    assert [m["id"] for m in nt.view()["messages"]] == ["9", "8", "7"]
