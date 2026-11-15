"""What every route module shares: role groups, limits and common checks."""

from __future__ import annotations

from fastapi import HTTPException

from .. import security
from ..auth import Auth, RateLimiter
from ..care import Ctx

CAREGIVERS = ("family", "caretaker")
READERS = ("family", "caretaker", "doctor")
EVERYONE = ("family", "caretaker", "doctor", "elder")
LIMITS = {"members": 12, "medicines": 40, "appointments": 200}


class Deps:
    """The context, storage, session helpers and checks each route module needs."""

    def __init__(self, ctx: Ctx) -> None:
        self.ctx = ctx
        self.store = ctx.store
        self.auth = Auth(ctx)
        self.allow = self.auth.allow
        self.start_session = self.auth.start_session
        self.sign_in_limit = RateLimiter(limit=20, window=60)
        self.create_limit = RateLimiter(limit=6, window=60)

    @staticmethod
    def public_member(member: dict, with_email: bool) -> dict:
        """A member as other people see them; email only for family."""
        shown = {k: member.get(k, "") for k in ("id", "name", "role", "phone")}
        if with_email:
            shown["email"] = member.get("email", "")
            shown["digest"] = member.get("digest", True)
        return shown

    def check_member_refs(self, pid: str, ids: list[str | None]) -> None:
        for member_id in ids:
            if member_id and not self.store.get(pid, "members", member_id):
                raise HTTPException(422, "That person is not in this orbit.")

    def check_limit(self, pid: str, kind: str) -> None:
        if len(self.store.list(pid, kind)) >= LIMITS[kind]:
            raise HTTPException(409, f"This orbit already has the most {kind} it can hold.")

    def passcode_fields(self, pid: str, passcode: str, skip_id: str | None = None) -> dict:
        """Validated, unique passcode, stored as a slow hash plus a fast lookup key."""
        try:
            security.validate_passcode(passcode)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        key = security.passcode_key(passcode, pid, self.ctx.settings.secret_key)
        for other in security.candidates_for(self.store.list(pid, "members"), key):
            if other["id"] != skip_id and security.verify_passcode(passcode, other["passcode_hash"]):
                raise HTTPException(422, "Please choose a different passcode.")
        return {"passcode_hash": security.hash_passcode(passcode), "passcode_key": key}
