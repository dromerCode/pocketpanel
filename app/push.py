import asyncio
import base64
import json
import logging
from pathlib import Path

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

log = logging.getLogger("pocketpanel.push")


class PushService:
    """Web Push con claves VAPID propias. Las suscripciones se guardan en un JSON."""

    def __init__(self, data_dir: str, contact: str = "mailto:admin@example.com"):
        self.dir = Path(data_dir)
        self.claims = {"sub": contact}
        self.key_file = self.dir / "vapid.pem"
        self.subs_file = self.dir / "push.json"
        self._vapid = None

    def _load(self) -> Vapid:
        if self._vapid is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            if not self.key_file.exists():
                v = Vapid()
                v.generate_keys()
                v.save_key(str(self.key_file))
            self._vapid = Vapid.from_file(str(self.key_file))
        return self._vapid

    def public_key(self) -> str:
        raw = self._load().public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    def subs(self) -> list:
        try:
            return json.loads(self.subs_file.read_text())
        except (OSError, ValueError):
            return []

    def _save(self, subs: list) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.subs_file.write_text(json.dumps(subs))

    def subscribe(self, sub: dict) -> None:
        if not isinstance(sub, dict) or not sub.get("endpoint") or not sub.get("keys"):
            raise ValueError("suscripción no válida")
        subs = [s for s in self.subs() if s["endpoint"] != sub["endpoint"]]
        self._save(subs + [{"endpoint": sub["endpoint"], "keys": sub["keys"]}])

    def unsubscribe(self, endpoint: str) -> None:
        self._save([s for s in self.subs() if s["endpoint"] != endpoint])

    def _send_sync(self, payload: str) -> int:
        self._load()
        sent, keep = 0, []
        for s in self.subs():
            try:
                webpush(s, payload, vapid_private_key=str(self.key_file), vapid_claims=dict(self.claims), ttl=3600)
                sent += 1
                keep.append(s)
            except WebPushException as e:
                code = getattr(e.response, "status_code", None)
                if code not in (404, 410):  # 404/410: el móvil ya no la quiere → se borra
                    keep.append(s)
                log.warning("push falló (%s): %s", code, e)
        self._save(keep)
        return sent

    async def send(self, title: str, body: str, url: str = "/") -> int:
        if not self.subs():
            return 0
        payload = json.dumps({"title": title, "body": body, "url": url})
        return await asyncio.to_thread(self._send_sync, payload)
