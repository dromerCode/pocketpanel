import time

import httpx

from ...core import UnavailableError


class JfaError(UnavailableError):
    pass


class Jfa:
    """Cliente mínimo de la API de administración de jfa-go (token Bearer, se renueva solo)."""

    def __init__(self, base: str, user: str, password: str, public_url: str, client: httpx.AsyncClient | None = None):
        self.base, self.user, self.password, self.public_url = base.rstrip("/"), user, password, public_url.rstrip("/")
        self.http = client or httpx.AsyncClient(timeout=20)
        self._token: str | None = None
        self._profile: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.user and self.password)

    async def _login(self) -> str:
        try:
            r = await self.http.get(f"{self.base}/token/login", auth=(self.user, self.password))
        except httpx.HTTPError as e:
            raise JfaError(f"jfa-go no responde: {e}") from e
        if r.status_code != 200:
            raise JfaError("jfa-go rechazó el usuario/contraseña de admin")
        self._token = r.json()["token"]
        return self._token

    async def _req(self, method: str, path: str, body=None):
        if not self.configured:
            raise JfaError("faltan PANEL_JFA_USER / PANEL_JFA_PASS en el .env")
        for attempt in (1, 2):
            token = self._token or await self._login()
            try:
                r = await self.http.request(method, f"{self.base}{path}", json=body,
                                            headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as e:
                raise JfaError(f"jfa-go no responde: {e}") from e
            if r.status_code == 401 and attempt == 1:
                self._token = None  # el token muere al reiniciar jfa-go
                continue
            if r.status_code >= 400:
                try:
                    msg = r.json().get("error") or r.text
                except ValueError:
                    msg = r.text
                raise JfaError(f"jfa-go: {msg}"[:300])
            return r.json() if r.content else {}
        raise JfaError("jfa-go: sin autorización")

    # ---------- usuarios ----------

    async def users(self) -> list:
        us = (await self._req("GET", "/users")).get("users") or []
        keep = ("id", "name", "email", "last_active", "admin", "expiry", "disabled", "label", "telegram")
        out = [{k: u.get(k) for k in keep} for u in us]
        return sorted(out, key=lambda u: u["name"].lower())

    async def create_user(self, username: str, password: str, email: str = "", months: int = 0) -> dict:
        if not username.strip() or len(password) < 6:
            raise JfaError("hace falta nombre y una contraseña de al menos 6 caracteres")
        await self._req("POST", "/user", {"username": username.strip(), "password": password,
                                          "email": email.strip(), "profile": await self.default_profile()})
        if months:
            u = next((u for u in await self.users() if u["name"].lower() == username.strip().lower()), None)
            if u:
                await self.extend([u["id"]], months=months)
        return {"ok": True}

    async def extend(self, ids: list, months: int = 0, days: int = 0, timestamp: int | None = None) -> None:
        body = {"users": ids, "notify": False}
        if timestamp:
            body["timestamp"] = int(timestamp)
        else:
            body.update(months=months, days=days)
        await self._req("POST", "/users/extend", body)

    async def remove_expiry(self, uid: str) -> None:
        await self._req("DELETE", f"/users/{uid}/expiry")

    async def enable(self, ids: list, enabled: bool) -> None:
        await self._req("POST", "/users/enable", {"users": ids, "enabled": enabled, "notify": False})

    async def delete(self, ids: list) -> None:
        await self._req("DELETE", "/users", {"users": ids, "notify": False})

    # ---------- invitaciones ----------

    async def default_profile(self) -> str:
        if self._profile is None:
            self._profile = (await self._req("GET", "/profiles")).get("default_profile") or ""
        return self._profile

    def link(self, code: str) -> str:
        return f"{self.public_url}/invite/{code}"

    async def invites(self) -> list:
        inv = (await self._req("GET", "/invites")).get("invites") or []
        out = []
        for i in inv:
            out.append({
                "code": i["code"], "label": i.get("label") or "", "link": self.link(i["code"]),
                "valid_till": i.get("valid_till"), "created": i.get("created"),
                "no_limit": i.get("no_limit", False), "remaining": i.get("remaining_uses", 0),
                "used_by": sorted((i.get("used_by") or {}).keys()),
                "user_months": i.get("user_months", 0) if i.get("user_expiry") else 0,
                "user_days": i.get("user_days", 0) if i.get("user_expiry") else 0,
            })
        return sorted(out, key=lambda i: -(i["created"] or 0))

    async def create_invite(self, label: str, uses: int, valid_days: int, user_months: int) -> dict:
        if valid_days < 1 or uses < 0:
            raise JfaError("datos de invitación no válidos")
        body = {
            "days": valid_days, "label": label.strip()[:60], "profile": await self.default_profile(),
            "multiple-uses": uses != 1, "no-limit": uses == 0, "remaining-uses": max(uses, 1),
            "user-expiry": user_months > 0,
        }
        if user_months > 0:
            body["user-months"] = user_months
        before = {i["code"] for i in await self.invites()}
        await self._req("POST", "/invites", body)
        new = [i for i in await self.invites() if i["code"] not in before]
        if not new:
            raise JfaError("jfa-go no devolvió la invitación nueva")
        return new[0]

    async def delete_invite(self, code: str) -> None:
        await self._req("DELETE", "/invites", {"code": code})


def expiry_state(expiry: int | None, now: float | None = None) -> str:
    """'none' | 'expired' | 'soon' (menos de 7 días) | 'ok'"""
    if not expiry:
        return "none"
    left = expiry - (now or time.time())
    return "expired" if left <= 0 else "soon" if left < 7 * 86400 else "ok"
