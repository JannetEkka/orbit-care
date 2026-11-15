"""The people in the circle, and the profile: about them, contacts and reminder rules."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import care, rules, security
from ..models import MemberIn, ProfileIn
from .deps import Deps


def register(router: APIRouter, d: Deps) -> None:
    ctx, store, allow, check_limit = d.ctx, d.store, d.allow, d.check_limit
    passcode_fields, public_member = d.passcode_fields, d.public_member

    @router.post("/api/members", status_code=201)
    def add_member(body: MemberIn, current: dict = Depends(allow("family"))) -> dict:
        pid = current["pid"]
        check_limit(pid, "members")
        if not body.passcode:
            raise HTTPException(422, "A new person needs a passcode.")
        doc = {
            "id": security.new_id("m"),
            "name": body.name,
            "role": body.role,
            "email": body.email,
            "phone": body.phone,
            "digest": body.digest,
            **passcode_fields(pid, body.passcode),
        }
        store.put(pid, "members", doc["id"], doc)
        care.audit(ctx, pid, current["member"], "person added", f"{doc['name']} ({doc['role']})")
        return public_member(doc, with_email=True)

    @router.put("/api/members/{member_id}")
    def edit_member(member_id: str, body: MemberIn, current: dict = Depends(allow("family"))) -> dict:
        pid = current["pid"]
        existing = store.get(pid, "members", member_id)
        if not existing:
            raise HTTPException(404, "No such person.")
        if member_id == current["member"]["id"] and body.role != "family":
            raise HTTPException(409, "You cannot remove your own family access.")
        existing.update(name=body.name, role=body.role, email=body.email, phone=body.phone, digest=body.digest)
        if body.passcode:
            existing.update(passcode_fields(pid, body.passcode, skip_id=member_id))
        store.put(pid, "members", member_id, existing)
        care.audit(ctx, pid, current["member"], "person changed", f"{existing['name']} ({existing['role']})")
        return public_member(existing, with_email=True)

    @router.delete("/api/members/{member_id}")
    def remove_member(member_id: str, current: dict = Depends(allow("family"))) -> dict:
        pid = current["pid"]
        existing = store.get(pid, "members", member_id)
        if not existing:
            raise HTTPException(404, "No such person.")
        if member_id == current["member"]["id"]:
            raise HTTPException(409, "You cannot remove yourself.")
        store.delete(pid, "members", member_id)
        care.audit(ctx, pid, current["member"], "person removed", f"{existing['name']} ({existing['role']})")
        return {"ok": True}

    @router.put("/api/profile")
    def edit_profile(body: ProfileIn, current: dict = Depends(allow("family"))) -> dict:
        settings = {**rules.settings_of(current["profile"]), **body.settings.model_dump()}
        if settings["escalate_after_min"] <= settings["missed_after_min"]:
            raise HTTPException(422, "The family alert must come after the first missed-dose reminder.")
        store.update_profile(
            current["pid"],
            {
                "elder_name": body.elder_name,
                "about": body.about.model_dump(),
                "contacts": body.contacts.model_dump(),
                "settings": settings,
            },
        )
        care.audit(ctx, current["pid"], current["member"], "profile changed", "about, contacts or rules")
        return {"ok": True}
