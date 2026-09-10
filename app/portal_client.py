"""The only module in this codebase that knows Urja Meter Ops exists.

Everything below reverse-engineers behaviour documented in detail in
PROTOCOL.md. In short:

- Auth is a SvelteKit form action at POST /login (better-auth under the
  hood) that sets an httpOnly session cookie good for ~1 hour. SvelteKit's
  CSRF guard requires a same-origin `Origin` header on the POST.
- Everything the UI shows is backed by JSON endpoints under /portal/* —
  there is no HTML to scrape. The one exception is /portal/export, a bulk
  endpoint that isn't linked from anywhere except the "Export all meters"
  button's JS, and requires an HMAC request signature on top of the
  session cookie (secret fetched from /portal/keys).
- We use /portal/export as the *primary* source for meter nameplate,
  hierarchy and geo data (one request for all ~400 meters) rather than
  hitting /meters/{id} 400+ times.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import httpx

from app.config import Settings
from app.portal_errors import MeterNotFoundError, PortalAuthError, PortalUnavailableError

# Observed in testing (see PROTOCOL.md): the session cookie's Max-Age is
# 3600s. httpx's cookie jar doesn't surface Max-Age back to us after
# storing the cookie, so rather than re-parsing the raw Set-Cookie header
# we just hardcode the observed lifetime. Worst case if the portal changes
# this: one spurious 401 -> one extra re-login, handled transparently.
ASSUMED_SESSION_TTL_SECONDS = 3600


class PortalClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.portal_base_url,
            timeout=settings.request_timeout_seconds,
        )
        self._session_expires_at: float | None = None
        self._signing_secret: str | None = None
        self._login_lock_held = False

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    # Auth
    # ------------------------------------------------------------------ #

    def session_active(self) -> bool:
        return self._session_expires_at is not None and time.monotonic() < self._session_expires_at

    async def _login(self) -> None:
        origin = self._settings.portal_base_url.rstrip("/")
        resp = await self._client.post(
            "/login",
            data={"email": self._settings.portal_email, "password": self._settings.portal_password},
            headers={
                # SvelteKit rejects cross-site form POSTs unless Origin matches
                # the host — see PROTOCOL.md "Auth workflow".
                "Origin": origin,
                "Referer": f"{origin}/login",
            },
        )
        body: dict | None
        try:
            body = resp.json()
        except ValueError:
            body = None

        if resp.status_code != 200 or not body or body.get("type") != "redirect":
            reason = (body or {}).get("data") if body else resp.text[:200]
            raise PortalAuthError(f"Portal login failed (status={resp.status_code}): {reason}")

        margin = self._settings.session_refresh_margin_seconds
        self._session_expires_at = time.monotonic() + ASSUMED_SESSION_TTL_SECONDS - margin
        # A fresh login *may* hand out a fresh signing secret; don't carry
        # a stale one across sessions.
        self._signing_secret = None

    async def _ensure_session(self) -> None:
        if not self.session_active():
            await self._login()

    async def check_session_alive(self) -> bool:
        """Used by /healthz — a lightweight, read-only session probe that
        doesn't force a login if we don't already have one."""
        if self._session_expires_at is None:
            return False
        try:
            resp = await self._client.get("/api/auth/get-session")
        except httpx.RequestError:
            return False
        return resp.status_code == 200 and "session" in (resp.json() or {})

    # ------------------------------------------------------------------ #
    # Low-level request helper: ensures auth, retries once on session
    # expiry, and translates transport/5xx failures into our own errors.
    # ------------------------------------------------------------------ #

    async def _authed_get(self, path: str, *, headers: dict | None = None) -> httpx.Response:
        await self._ensure_session()
        try:
            resp = await self._client.get(path, headers=headers)
        except httpx.RequestError as exc:
            raise PortalUnavailableError(f"Could not reach portal: {exc}") from exc

        if resp.status_code == 401:
            # Session died earlier than expected (or was revoked server-side).
            # Re-login once and retry; if it fails again, something's
            # actually wrong rather than just an expired cookie.
            self._session_expires_at = None
            await self._ensure_session()
            try:
                resp = await self._client.get(path, headers=headers)
            except httpx.RequestError as exc:
                raise PortalUnavailableError(f"Could not reach portal: {exc}") from exc

        if resp.status_code >= 500:
            raise PortalUnavailableError(f"Portal returned {resp.status_code} for {path}")

        return resp

    # ------------------------------------------------------------------ #
    # Bulk export (signed)
    # ------------------------------------------------------------------ #

    async def _get_signing_secret(self) -> str:
        if self._signing_secret is not None:
            return self._signing_secret
        resp = await self._authed_get("/portal/keys")
        if resp.status_code != 200:
            raise PortalUnavailableError(f"Could not fetch signing key (status={resp.status_code})")
        self._signing_secret = resp.json()["data"]["signingSecret"]
        return self._signing_secret

    @staticmethod
    def _sign(method: str, path: str, query: str, timestamp: str, secret: str) -> str:
        message = f"{method}\n{path}\n{query}\n{timestamp}".encode()
        return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()

    async def fetch_all_meters(self) -> list[dict]:
        """Fetch the full meter dataset via the bulk export endpoint.

        Quirk (see PROTOCOL.md): /portal/export accepts a `page` query
        param — and it must be included in the signed string — but the
        server ignores it and always returns every meter. So one call is
        the whole dataset; we don't need to loop pages here.
        """
        secret = await self._get_signing_secret()
        query = "page=1"
        timestamp = str(int(time.time()))
        signature = self._sign("GET", "/portal/export", query, timestamp, secret)

        resp = await self._authed_get(
            f"/portal/export?{query}",
            headers={"x-timestamp": timestamp, "x-signature": signature},
        )
        if resp.status_code == 401:
            # Signature rejected — most likely our cached secret rotated
            # server-side. Refetch once and retry.
            self._signing_secret = None
            secret = await self._get_signing_secret()
            signature = self._sign("GET", "/portal/export", query, timestamp, secret)
            resp = await self._authed_get(
                f"/portal/export?{query}",
                headers={"x-timestamp": timestamp, "x-signature": signature},
            )
        if resp.status_code != 200:
            raise PortalUnavailableError(f"Bulk export failed (status={resp.status_code}): {resp.text[:200]}")
        return resp.json()["data"]

    # ------------------------------------------------------------------ #
    # Transformers (DTs) — small enough to page through in full.
    # ------------------------------------------------------------------ #

    async def fetch_all_transformers(self) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            resp = await self._authed_get(f"/portal/dts?page={page}")
            if resp.status_code != 200:
                raise PortalUnavailableError(f"DT listing failed (status={resp.status_code})")
            body = resp.json()
            out.extend(body["data"])
            if len(out) >= body["total"] or not body["data"]:
                break
            page += 1
        return out

    # ------------------------------------------------------------------ #
    # Per-meter consumption
    # ------------------------------------------------------------------ #

    async def fetch_meter_energy(self, meter_id: str) -> list[dict]:
        resp = await self._authed_get(f"/portal/meters/{meter_id}/energy")
        if resp.status_code == 404:
            raise MeterNotFoundError(meter_id)
        if resp.status_code != 200:
            raise PortalUnavailableError(f"Energy fetch failed for {meter_id} (status={resp.status_code})")
        return resp.json()["data"]
