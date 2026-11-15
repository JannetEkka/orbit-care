"""Sessions, roles and rate limits.

A session is a signed, expiring token in an HttpOnly, SameSite=Strict cookie. Every
request re-reads the member from storage, so removing a person ends their access at
once. `Auth.allow(*roles)` is the FastAPI dependency each route uses.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response

from . import security
from .care import Ctx

COOKIE = "orbit_session"
SECURE_COOKIE = "__Host-orbit_session"  # browsers only accept it over HTTPS, host-only, path /
SESSION_TTL = {"elder": timedelta(days=30)}  # the bedside tablet stays signed in
DEFAULT_TTL = timedelta(hours=12)
MAX_TRACKED_CLIENTS = 5000


class RateLimiter:
    """At most `limit` calls per `window` seconds for each client address."""

    def __init__(self, limit: int, window: float) -> None:
        self._limit, self._window = limit, window
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, client: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(client, []) if now - t < self._window]
            if len(hits) >= self._limit:
                raise HTTPException(429, "Too many attempts. Please wait a minute.")
            hits.append(now)
            self._hits[client] = hits
            if len(self._hits) > MAX_TRACKED_CLIENTS:
                self._hits.clear()


def client_of(request: Request) -> str:
    """The caller's address, taking the first hop behind the host's proxy."""
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")


def cookie_name(secure: bool) -> str:
    return SECURE_COOKIE if secure else COOKIE


class Auth:
    def __init__(self, ctx: Ctx) -> None:
        self._ctx = ctx
        self.cookie = cookie_name(ctx.settings.cookie_secure)

    def start_session(self, response: Response, pid: str, member: dict) -> None:
        ttl = SESSION_TTL.get(member["role"], DEFAULT_TTL)
        token = security.make_token(
            {"pid": pid, "mid": member["id"]}, self._ctx.settings.secret_key, self._ctx.clock(), ttl
        )
        response.set_cookie(
            self.cookie,
            token,
            max_age=int(ttl.total_seconds()),
            httponly=True,
            secure=self._ctx.settings.cookie_secure,
            samesite="strict",
            path="/",
        )

    def session(self, request: Request) -> dict:
        """The signed-in member, re-read from storage so removed members lose access."""
        ctx = self._ctx
        payload = security.read_token(request.cookies.get(self.cookie, ""), ctx.settings.secret_key, ctx.clock())
        if not payload:
            raise HTTPException(401, "Please sign in.")
        profile = ctx.store.get_profile(payload["pid"])
        member = ctx.store.get(payload["pid"], "members", payload["mid"]) if profile else None
        if not profile or not member:
            raise HTTPException(401, "Please sign in.")
        return {"pid": payload["pid"], "profile": profile, "member": member}

    def allow(self, *roles: str) -> Callable[..., dict]:
        """Dependency: the current session, if the member's role is one of `roles`."""
        session = self.session

        def dependency(current: dict = Depends(session)) -> dict:
            if current["member"]["role"] not in roles:
                raise HTTPException(403, "Your role cannot do this.")
            return current

        return dependency
