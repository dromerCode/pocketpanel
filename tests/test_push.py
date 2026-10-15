import base64

from app.push import PushService


def test_keys_persist_and_public_key_format(tmp_path):
    p = PushService(str(tmp_path))
    k = p.public_key()
    raw = base64.urlsafe_b64decode(k + "=" * (-len(k) % 4))
    assert len(raw) == 65 and raw[0] == 4  # punto P-256 sin comprimir
    assert PushService(str(tmp_path)).public_key() == k


def test_subscribe_dedupes_and_validates(tmp_path):
    p = PushService(str(tmp_path))
    sub = {"endpoint": "https://fcm/x", "keys": {"p256dh": "a", "auth": "b"}, "expirationTime": None}
    p.subscribe(sub)
    p.subscribe(sub)
    assert len(p.subs()) == 1 and "expirationTime" not in p.subs()[0]
    p.unsubscribe("https://fcm/x")
    assert p.subs() == []
    try:
        p.subscribe({"endpoint": ""})
        assert False
    except ValueError:
        pass


async def test_send_without_subs_is_noop(tmp_path):
    assert await PushService(str(tmp_path)).send("t", "b") == 0


async def test_send_uses_configured_contact(tmp_path, monkeypatch):
    import app.push as push_mod
    seen = {}
    monkeypatch.setattr(push_mod, "webpush", lambda s, payload, **kw: seen.update(kw))
    p = PushService(str(tmp_path), "mailto:ramon@example.org")
    p.subscribe({"endpoint": "https://fcm/x", "keys": {"p256dh": "a", "auth": "b"}})
    assert await p.send("t", "b") == 1
    assert seen["vapid_claims"] == {"sub": "mailto:ramon@example.org"}
