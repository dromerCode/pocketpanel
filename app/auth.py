import base64
import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request, WebSocket
from itsdangerous import BadSignature, TimestampSigner

COOKIE = "panel"
TOKEN_MAX_AGE = 30 * 24 * 3600
MAX_FAILS = 5
LOCK_SECONDS = 300

_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pin.encode(), salt=salt, **_SCRYPT)
    return "scrypt:" + base64.b64encode(salt).decode() + ":" + base64.b64encode(dk).decode()


def verify_pin(pin: str, stored: str) -> bool:
    try:
        _, salt, dk = stored.split(":")
        got = hashlib.scrypt(pin.encode(), salt=base64.b64decode(salt), **_SCRYPT)
        return hmac.compare_digest(got, base64.b64decode(dk))
    except Exception:
        return False


def make_token(secret: str) -> str:
    return TimestampSigner(secret).sign(b"ok").decode()


def check_token(token: str, secret: str) -> bool:
    if not token:
        return False
    try:
        TimestampSigner(secret).unsign(token, max_age=TOKEN_MAX_AGE)
        return True
    except BadSignature:
        return False


class LoginLimiter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.fails: dict[str, list[float]] = {}

    def allowed(self, ip: str) -> bool:
        now = self.clock()
        recent = [t for t in self.fails.get(ip, []) if now - t < LOCK_SECONDS]
        self.fails[ip] = recent
        return len(recent) < MAX_FAILS

    def fail(self, ip: str) -> None:
        self.fails.setdefault(ip, []).append(self.clock())

    def ok(self, ip: str) -> None:
        self.fails.pop(ip, None)


def require_auth(request: Request) -> None:
    if not check_token(request.cookies.get(COOKIE, ""), request.app.state.cfg.secret):
        raise HTTPException(401, "no autenticado")


async def ws_authed(ws: WebSocket) -> bool:
    if check_token(ws.cookies.get(COOKIE, ""), ws.app.state.cfg.secret):
        return True
    await ws.close(code=4401)
    return False
