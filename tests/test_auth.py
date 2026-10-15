import time

from app import auth


def test_pin_roundtrip():
    h = auth.hash_pin("1234")
    assert auth.verify_pin("1234", h)
    assert not auth.verify_pin("4321", h)


def test_verify_pin_garbage_hash():
    assert not auth.verify_pin("1234", "nope")


def test_token_valid_and_tampered():
    tok = auth.make_token("secret")
    assert auth.check_token(tok, "secret")
    assert not auth.check_token(tok + "x", "secret")
    assert not auth.check_token(tok, "other")
    assert not auth.check_token("", "secret")


def test_token_expired(monkeypatch):
    tok = auth.make_token("secret")
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + auth.TOKEN_MAX_AGE + 10)
    assert not auth.check_token(tok, "secret")


def test_limiter_blocks_after_five_and_releases(monkeypatch):
    now = [1000.0]
    lim = auth.LoginLimiter(clock=lambda: now[0])
    for _ in range(5):
        assert lim.allowed("1.2.3.4")
        lim.fail("1.2.3.4")
    assert not lim.allowed("1.2.3.4")
    assert lim.allowed("5.6.7.8")
    now[0] += auth.LOCK_SECONDS + 1
    assert lim.allowed("1.2.3.4")


def test_limiter_ok_resets():
    lim = auth.LoginLimiter()
    for _ in range(4):
        lim.fail("a")
    lim.ok("a")
    for _ in range(4):
        lim.fail("a")
    assert lim.allowed("a")
