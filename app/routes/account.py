"""Sign in, sign out, start a circle, open a sample family."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import care, notify, rules, security
from ..auth import client_of
from ..demo import seed_demo
from ..models import CreateOrbitIn, LoginIn
from .deps import EVERYONE, Deps

WRONG = "That orbit code and passcode do not match."


def register(router: APIRouter, d: Deps) -> None:
    ctx, store, auth, allow, start_session = d.ctx, d.store, d.auth, d.allow, d.start_session
    sign_in_limit, create_limit, passcode_fields, public_member = (
        d.sign_in_limit,
        d.create_limit,
        d.passcode_fields,
        d.public_member,
    )

    @router.post("/api/login")
    def login(body: LoginIn, request: Request, response: Response) -> dict:
        sign_in_limit.check(client_of(request))
        now = ctx.clock()
        profile = store.get_profile(body.orbit_code)
        if not profile:
            security.hash_passcode(body.passcode)  # same work either way: no timing hint
            raise HTTPException(401, WRONG)
        if security.is_locked(profile, now):
            raise HTTPException(423, "Too many wrong passcodes. Try again in 15 minutes.")
        key = security.passcode_key(body.passcode, body.orbit_code, ctx.settings.secret_key)
        for member in security.candidates_for(store.list(body.orbit_code, "members"), key):
            if security.verify_passcode(body.passcode, member["passcode_hash"]):
                if member.get("passcode_key") != key:  # older record: add its lookup key
                    store.put(body.orbit_code, "members", member["id"], {**member, "passcode_key": key})
                store.update_profile(body.orbit_code, {"failed_attempts": 0, "locked_until": None})
                start_session(response, body.orbit_code, member)
                return {"role": member["role"], "name": member["name"]}
        store.update_profile(body.orbit_code, security.after_failed_attempt(profile, now))
        raise HTTPException(401, WRONG)

    @router.post("/api/logout")
    def logout(response: Response) -> dict:
        response.delete_cookie(
            auth.cookie, path="/", secure=ctx.settings.cookie_secure, httponly=True, samesite="strict"
        )
        return {"ok": True}

    @router.post("/api/orbits", status_code=201)
    def create_orbit(body: CreateOrbitIn, request: Request, response: Response) -> dict:
        create_limit.check(client_of(request))
        try:
            security.validate_passcode(body.passcode)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        now = ctx.clock()
        pid = security.new_orbit_code()
        profile = {
            "id": pid,
            "elder_name": body.elder_name,
            "about": {},
            "contacts": {"ambulance_phone": "108"},
            "settings": dict(rules.DEFAULT_SETTINGS),
            "created_at": now.isoformat(),
            "created_on": care.local_now({"settings": {}}, now).date().isoformat(),
            "demo": False,
        }
        if not store.create_profile(pid, profile):
            raise HTTPException(503, "Please try again.")
        member = {
            "id": security.new_id("m"),
            "name": body.your_name,
            "role": "family",
            "email": body.your_email,
            "phone": "",
            "digest": True,
            **passcode_fields(pid, body.passcode),
        }
        store.put(pid, "members", member["id"], member)
        care.audit(ctx, pid, member, "orbit created", f"for {body.elder_name}")
        start_session(response, pid, member)
        return {"orbit_code": pid, "role": "family"}

    @router.post("/api/demo", status_code=201)
    def create_demo(request: Request, response: Response) -> dict:
        create_limit.check(client_of(request))
        if len(store.list_profile_ids()) >= ctx.settings.max_demo_orbits:
            raise HTTPException(503, "The demo is busy. Please try again later.")
        pid, passcodes, family = seed_demo(ctx)
        notify.tick_profile(ctx, pid)  # so the Emails tab shows what Orbit would send
        start_session(response, pid, family)
        return {"orbit_code": pid, "passcodes": passcodes, "role": "family"}

    @router.get("/api/me")
    def me(current: dict = Depends(allow(*EVERYONE))) -> dict:
        return {
            "orbit_code": current["pid"],
            "elder_name": current["profile"]["elder_name"],
            "demo": bool(current["profile"].get("demo")),
            "member": public_member(current["member"], with_email=False),
        }
