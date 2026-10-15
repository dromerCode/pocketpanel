import json

import httpx
import pytest

from app.jfa import Jfa, JfaError, expiry_state


def make(handler):
    return Jfa("http://jfa", "admin", "pw", "https://pub.example", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_expiry_state():
    assert expiry_state(0) == "none"
    assert expiry_state(100, now=200) == "expired"
    assert expiry_state(200 + 3 * 86400, now=200) == "soon"
    assert expiry_state(200 + 30 * 86400, now=200) == "ok"


async def test_relogin_on_401_and_users_sorted():
    calls = {"login": 0, "users": 0}

    def h(req):
        if req.url.path == "/token/login":
            calls["login"] += 1
            return httpx.Response(200, json={"token": f"t{calls['login']}"})
        if req.url.path == "/users":
            calls["users"] += 1
            if req.headers["authorization"] == "Bearer t1":
                return httpx.Response(401)  # token viejo (jfa-go reiniciado)
            return httpx.Response(200, json={"users": [{"id": "2", "name": "zeta"}, {"id": "1", "name": "Ana", "expiry": 5}]})
        return httpx.Response(404)

    j = make(h)
    us = await j.users()
    assert [u["name"] for u in us] == ["Ana", "zeta"] and calls == {"login": 2, "users": 2}


async def test_bad_credentials():
    j = make(lambda req: httpx.Response(401))
    with pytest.raises(JfaError, match="rechazó"):
        await j.users()


async def test_not_configured():
    j = Jfa("http://jfa", "", "", "https://pub")
    with pytest.raises(JfaError, match="PANEL_JFA_USER"):
        await j.users()


async def test_create_invite_body_and_returns_new():
    state = {"invites": [{"code": "old", "created": 1}], "posted": None}

    def h(req):
        p = req.url.path
        if p == "/token/login":
            return httpx.Response(200, json={"token": "t"})
        if p == "/profiles":
            return httpx.Response(200, json={"default_profile": "plantilla", "profiles": {}})
        if p == "/invites" and req.method == "GET":
            return httpx.Response(200, json={"invites": state["invites"]})
        if p == "/invites" and req.method == "POST":
            state["posted"] = json.loads(req.content)
            state["invites"] = state["invites"] + [{"code": "NEW", "created": 2, "user_expiry": True, "user_months": 3,
                                                    "remaining_uses": 1}]
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404)

    j = make(h)
    inv = await j.create_invite("Para Pepe", uses=1, valid_days=7, user_months=3)
    assert inv["code"] == "NEW" and inv["link"] == "https://pub.example/invite/NEW" and inv["user_months"] == 3
    b = state["posted"]
    assert b["profile"] == "plantilla" and b["days"] == 7 and b["user-expiry"] is True and b["user-months"] == 3
    assert b["multiple-uses"] is False and b["no-limit"] is False and b["remaining-uses"] == 1


async def test_unlimited_invite_flags():
    posted = {}

    def h(req):
        if req.url.path == "/token/login":
            return httpx.Response(200, json={"token": "t"})
        if req.url.path == "/profiles":
            return httpx.Response(200, json={"default_profile": "p"})
        if req.method == "POST":
            posted.update(json.loads(req.content))
            return httpx.Response(200, json={})
        n = 1 if posted else 0
        return httpx.Response(200, json={"invites": [{"code": "X", "created": 1}] if n else None})

    j = make(h)
    await j.create_invite("", uses=0, valid_days=30, user_months=0)
    assert posted["no-limit"] is True and posted["multiple-uses"] is True and posted["user-expiry"] is False


async def test_create_user_validation():
    j = make(lambda req: httpx.Response(200, json={}))
    with pytest.raises(JfaError):
        await j.create_user("pepe", "123")
