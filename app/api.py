"""HTTP API. Every route checks the signed session and the member's role."""

from __future__ import annotations

import hmac
import threading
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from . import care, notify, rules, security
from .care import Ctx
from .demo import seed_demo
from .models import (
    AppointmentIn,
    CreateOrbitIn,
    DoctorRequestIn,
    FeelingIn,
    LoginIn,
    MarkIn,
    MedicineIn,
    MemberIn,
    NoteIn,
    ProfileIn,
)

COOKIE = "orbit_session"
SESSION_TTL = {"elder": timedelta(days=30)}
DEFAULT_TTL = timedelta(hours=12)
CAREGIVERS = ("family", "caretaker")
READERS = ("family", "caretaker", "doctor")
EVERYONE = ("family", "caretaker", "doctor", "elder")
LIMITS = {"members": 12, "medicines": 40, "appointments": 200}
HELP_COOLDOWN = timedelta(seconds=60)
WRONG = "That orbit code and passcode do not match."


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
            if len(self._hits) > 5000:
                self._hits.clear()


def build_router(ctx: Ctx) -> APIRouter:
    router = APIRouter()
    store = ctx.store
    sign_in_limit = RateLimiter(limit=20, window=60)
    create_limit = RateLimiter(limit=6, window=60)

    # ---------- session helpers ----------

    def client_of(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        return forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")

    def start_session(response: Response, pid: str, member: dict) -> None:
        ttl = SESSION_TTL.get(member["role"], DEFAULT_TTL)
        token = security.make_token({"pid": pid, "mid": member["id"]}, ctx.settings.secret_key, ctx.clock(), ttl)
        response.set_cookie(
            COOKIE,
            token,
            max_age=int(ttl.total_seconds()),
            httponly=True,
            secure=ctx.settings.cookie_secure,
            samesite="strict",
            path="/",
        )

    def session(request: Request) -> dict:
        """The signed-in member, re-read from storage so removed members lose access."""
        payload = security.read_token(request.cookies.get(COOKIE, ""), ctx.settings.secret_key, ctx.clock())
        if not payload:
            raise HTTPException(401, "Please sign in.")
        profile = store.get_profile(payload["pid"])
        member = store.get(payload["pid"], "members", payload["mid"]) if profile else None
        if not profile or not member:
            raise HTTPException(401, "Please sign in.")
        return {"pid": payload["pid"], "profile": profile, "member": member}

    def allow(*roles: str):
        def dependency(current: dict = Depends(session)) -> dict:
            if current["member"]["role"] not in roles:
                raise HTTPException(403, "Your role cannot do this.")
            return current

        return dependency

    def public_member(member: dict, with_email: bool) -> dict:
        shown = {k: member.get(k, "") for k in ("id", "name", "role", "phone")}
        if with_email:
            shown["email"] = member.get("email", "")
            shown["digest"] = member.get("digest", True)
        return shown

    def check_member_refs(pid: str, ids: list[str | None]) -> None:
        for member_id in ids:
            if member_id and not store.get(pid, "members", member_id):
                raise HTTPException(422, "That person is not in this orbit.")

    def check_limit(pid: str, kind: str) -> None:
        if len(store.list(pid, kind)) >= LIMITS[kind]:
            raise HTTPException(409, f"This orbit already has the most {kind} it can hold.")

    def passcode_hash_for(pid: str, passcode: str, skip_id: str | None = None) -> str:
        try:
            security.validate_passcode(passcode)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        for other in store.list(pid, "members"):
            if other["id"] != skip_id and security.verify_passcode(passcode, other["passcode_hash"]):
                raise HTTPException(422, "Please choose a different passcode.")
        return security.hash_passcode(passcode)

    # ---------- sign in, sign out, create ----------

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
        for member in store.list(body.orbit_code, "members"):
            if security.verify_passcode(body.passcode, member["passcode_hash"]):
                store.update_profile(body.orbit_code, {"failed_attempts": 0, "locked_until": None})
                start_session(response, body.orbit_code, member)
                return {"role": member["role"], "name": member["name"]}
        store.update_profile(body.orbit_code, security.after_failed_attempt(profile, now))
        raise HTTPException(401, WRONG)

    @router.post("/api/logout")
    def logout(response: Response) -> dict:
        response.delete_cookie(COOKIE, path="/")
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
            "passcode_hash": security.hash_passcode(body.passcode),
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

    # ---------- today ----------

    @router.get("/api/today")
    def today(day: date | None = None, current: dict = Depends(allow(*READERS))) -> dict:
        pid, profile = current["pid"], current["profile"]
        now = care.local_now(profile, ctx.clock())
        day = day or now.date()
        if abs((day - now.date()).days) > 60:
            raise HTTPException(422, "That date is too far away.")
        settings = rules.settings_of(profile)
        meds = store.list(pid, "medicines")
        appointments = store.list(pid, "appointments")
        is_family = current["member"]["role"] == "family"
        return {
            "now": now.isoformat(),
            "date": day.isoformat(),
            "is_today": day == now.date(),
            "elder_name": profile["elder_name"],
            "doses": rules.day_view(meds, care.load_events(store, pid, day, day), day, now, settings),
            "members": [public_member(m, is_family) for m in store.list(pid, "members")],
            "feeling": (store.get(pid, "feelings", day.isoformat()) or {}).get("value"),
            "refill": rules.refill_warnings(meds, settings),
            "checkups": rules.checkups_due(appointments, now),
            "upcoming_appointments": sorted(
                (a for a in appointments if a["when"] >= now.isoformat()), key=lambda a: a["when"]
            )[:3],
            "about": profile.get("about", {}),
            "contacts": profile.get("contacts", {}),
            "settings": settings,
        }

    def find_dose(pid: str, key: str, now: datetime) -> rules.Dose:
        """Resolve a dose key to a real scheduled dose, or refuse it."""
        try:
            med_id, day_text, _ = key.rsplit("_", 2)
            day = date.fromisoformat(day_text)
        except ValueError as error:
            raise HTTPException(404, "No such dose.") from error
        med = store.get(pid, "medicines", med_id)
        dose = next((d for d in rules.doses_for_day([med] if med else [], day) if d.key == key), None)
        if not dose:
            raise HTTPException(404, "No such dose.")
        if dose.due_at > now + timedelta(hours=2) or dose.due_at < now - timedelta(days=3):
            raise HTTPException(409, "This dose cannot be marked now.")
        return dose

    @router.post("/api/doses/{key}/mark")
    def mark_dose(key: str, body: MarkIn, current: dict = Depends(allow("family", "caretaker", "elder"))) -> dict:
        pid, member = current["pid"], current["member"]
        if member["role"] == "elder" and body.status != "given":
            raise HTTPException(403, "The bedside screen can only confirm a dose.")
        now = care.local_now(current["profile"], ctx.clock())
        dose = find_dose(pid, key, now)
        previous = store.get(pid, "doses", key)
        was_given = bool(previous) and previous.get("status") == "given"
        store.put(
            pid,
            "doses",
            key,
            {
                "key": key,
                "med_id": dose.med_id,
                "date": dose.due_at.date().isoformat(),
                "time": dose.time,
                "status": body.status,
                "reason": body.reason,
                "by_id": member["id"],
                "by_name": member["name"],
                "by_role": member["role"],
                "at": now.isoformat(),
            },
        )
        med = store.get(pid, "medicines", dose.med_id)
        change = (body.status == "given") - was_given
        if med and med.get("stock") is not None and change:
            med["stock"] = max(0, med["stock"] - change * int(med.get("per_dose", 1)))
            store.put(pid, "medicines", med["id"], med)
        care.audit(ctx, pid, member, f"dose {body.status}", f"{dose.name} {dose.time} {body.reason}")
        return {"ok": True, "state": body.status}

    @router.delete("/api/doses/{key}/mark")
    def unmark_dose(key: str, current: dict = Depends(allow(*CAREGIVERS))) -> dict:
        """Undo a mark made by mistake: the dose goes back to due or missed, stock is restored."""
        pid, member = current["pid"], current["member"]
        now = care.local_now(current["profile"], ctx.clock())
        dose = find_dose(pid, key, now)
        previous = store.get(pid, "doses", key)
        if not previous:
            return {"ok": True}
        store.delete(pid, "doses", key)
        med = store.get(pid, "medicines", dose.med_id)
        if previous.get("status") == "given" and med and med.get("stock") is not None:
            med["stock"] += int(med.get("per_dose", 1))
            store.put(pid, "medicines", med["id"], med)
        care.audit(ctx, pid, member, "dose mark undone", f"{dose.name} {dose.time}")
        return {"ok": True}

    @router.post("/api/feeling")
    def feeling(body: FeelingIn, current: dict = Depends(allow("family", "caretaker", "elder"))) -> dict:
        now = care.local_now(current["profile"], ctx.clock())
        day = now.date().isoformat()
        store.put(
            current["pid"],
            "feelings",
            day,
            {"date": day, "value": body.value, "at": now.isoformat(), "by_role": current["member"]["role"]},
        )
        return {"ok": True}

    # ---------- bedside ----------

    @router.get("/api/bedside")
    def bedside(current: dict = Depends(allow("elder", "family", "caretaker"))) -> dict:
        pid, profile = current["pid"], current["profile"]
        now = care.local_now(profile, ctx.clock())
        settings = rules.settings_of(profile)
        view = rules.day_view(
            store.list(pid, "medicines"),
            care.load_events(store, pid, now.date(), now.date()),
            now.date(),
            now,
            settings,
        )
        recent = (now - timedelta(hours=3)).strftime("%H:%M")
        due = [d for d in view if d["state"] == "due" or (d["state"] == "missed" and d["time"] >= recent)]
        upcoming = [d for d in view if d["state"] == "upcoming"]
        name = (profile.get("about") or {}).get("address_as") or profile["elder_name"]
        contacts = profile.get("contacts", {})
        members = store.list(pid, "members")
        people = [
            {"name": m["name"], "role": m["role"], "phone": m["phone"]}
            for m in members
            if m.get("phone") and m["role"] != "elder"
        ]
        circle = [m["name"].split(" (")[0] for m in members if m["role"] in CAREGIVERS]
        return {
            "now": now.isoformat(),
            "name": name,
            "due": due,
            "next": upcoming[0] if upcoming else None,
            "done_today": sum(1 for d in view if d["state"] == "given"),
            "total_today": len(view),
            "feeling": (store.get(pid, "feelings", now.date().isoformat()) or {}).get("value"),
            "speak": f"{name}, it is time for your medicine." if due else "",
            "people": people,
            "circle": circle[:4],
            "night": now.hour >= 21 or now.hour < 6,
            "ambulance_phone": contacts.get("ambulance_phone", "108"),
        }

    @router.post("/api/help")
    def press_help(current: dict = Depends(allow(*EVERYONE))) -> dict:
        pid, profile, member = current["pid"], current["profile"], current["member"]
        utc_now = ctx.clock()
        last = profile.get("last_help_at")
        if last and datetime.fromisoformat(last) > utc_now - HELP_COOLDOWN:
            return {"ok": True, "told": profile.get("last_help_told", []), "repeat": True}
        now = care.local_now(profile, utc_now)
        circle = [m for m in store.list(pid, "members") if m["role"] in CAREGIVERS and m.get("email")]
        facts = {"time": now.strftime("%H:%M"), "by": member["name"]}
        key = f"help_{utc_now.strftime('%Y%m%dT%H%M%S')}"
        notify.deliver(ctx, pid, profile, key, "help", circle, facts)
        told = [m["name"] for m in circle]
        store.update_profile(pid, {"last_help_at": utc_now.isoformat(), "last_help_told": told})
        care.audit(ctx, pid, member, "help pressed", f"told {len(told)} people")
        return {"ok": True, "told": told, "repeat": False}

    # ---------- medicines ----------

    @router.get("/api/medicines")
    def list_medicines(current: dict = Depends(allow(*READERS))) -> list[dict]:
        meds = store.list(current["pid"], "medicines")
        for med in meds:
            left = rules.days_of_stock(med)
            med["days_left"] = None if left is None else int(left)
        return sorted(meds, key=lambda m: m["name"].lower())

    def medicine_doc(body: MedicineIn, existing: dict | None, today_text: str) -> dict:
        slots = sorted({s.time: s.giver_id for s in body.slots}.items())
        doc = {
            **(existing or {"id": security.new_id("med"), "start_date": today_text}),
            "name": body.name,
            "dose": body.dose,
            "instructions": body.instructions,
            "slots": [{"time": t, "giver_id": g} for t, g in slots],
            "per_dose": body.per_dose,
            "colour": body.colour,
            "active": body.active,
        }
        if body.stock != (existing or {}).get("stock"):
            doc["stock"], doc["stock_set_on"] = body.stock, today_text
        return doc

    @router.post("/api/medicines", status_code=201)
    def add_medicine(body: MedicineIn, current: dict = Depends(allow(*CAREGIVERS))) -> dict:
        pid = current["pid"]
        check_limit(pid, "medicines")
        check_member_refs(pid, [s.giver_id for s in body.slots])
        today_text = care.local_now(current["profile"], ctx.clock()).date().isoformat()
        doc = medicine_doc(body, None, today_text)
        store.put(pid, "medicines", doc["id"], doc)
        care.audit(ctx, pid, current["member"], "medicine added", f"{doc['name']} {doc['dose']}")
        return doc

    @router.put("/api/medicines/{med_id}")
    def edit_medicine(med_id: str, body: MedicineIn, current: dict = Depends(allow(*CAREGIVERS))) -> dict:
        pid = current["pid"]
        existing = store.get(pid, "medicines", med_id)
        if not existing:
            raise HTTPException(404, "No such medicine.")
        check_member_refs(pid, [s.giver_id for s in body.slots])
        today_text = care.local_now(current["profile"], ctx.clock()).date().isoformat()
        doc = medicine_doc(body, existing, today_text)
        store.put(pid, "medicines", med_id, doc)
        care.audit(ctx, pid, current["member"], "medicine changed", f"{doc['name']} {doc['dose']}")
        return doc

    @router.delete("/api/medicines/{med_id}")
    def stop_medicine(med_id: str, current: dict = Depends(allow(*CAREGIVERS))) -> dict:
        """Stopping keeps the history: the medicine ends today, it is not erased."""
        pid = current["pid"]
        existing = store.get(pid, "medicines", med_id)
        if not existing:
            raise HTTPException(404, "No such medicine.")
        today_text = care.local_now(current["profile"], ctx.clock()).date().isoformat()
        existing.update(active=False, end_date=today_text)
        store.put(pid, "medicines", med_id, existing)
        care.audit(ctx, pid, current["member"], "medicine stopped", existing["name"])
        return {"ok": True}

    # ---------- appointments ----------

    @router.get("/api/appointments")
    def list_appointments(current: dict = Depends(allow(*READERS))) -> list[dict]:
        return sorted(store.list(current["pid"], "appointments"), key=lambda a: a["when"])

    def appointment_doc(body: AppointmentIn, appt_id: str) -> dict:
        return {
            "id": appt_id,
            "doctor": body.doctor,
            "purpose": body.purpose,
            "when": body.when.replace(tzinfo=None, second=0, microsecond=0).isoformat(),
            "clinic_phone": body.clinic_phone,
            "accompany_id": body.accompany_id,
            "repeat_days": body.repeat_days,
        }

    @router.post("/api/appointments", status_code=201)
    def add_appointment(body: AppointmentIn, current: dict = Depends(allow(*CAREGIVERS))) -> dict:
        pid = current["pid"]
        check_limit(pid, "appointments")
        check_member_refs(pid, [body.accompany_id])
        doc = appointment_doc(body, security.new_id("ap"))
        store.put(pid, "appointments", doc["id"], doc)
        care.audit(ctx, pid, current["member"], "appointment added", f"{doc['doctor']} {doc['when']}")
        return doc

    @router.put("/api/appointments/{appt_id}")
    def edit_appointment(appt_id: str, body: AppointmentIn, current: dict = Depends(allow(*CAREGIVERS))) -> dict:
        pid = current["pid"]
        if not store.get(pid, "appointments", appt_id):
            raise HTTPException(404, "No such appointment.")
        check_member_refs(pid, [body.accompany_id])
        doc = appointment_doc(body, appt_id)
        store.put(pid, "appointments", appt_id, doc)
        care.audit(ctx, pid, current["member"], "appointment changed", f"{doc['doctor']} {doc['when']}")
        return doc

    @router.delete("/api/appointments/{appt_id}")
    def delete_appointment(appt_id: str, current: dict = Depends(allow(*CAREGIVERS))) -> dict:
        pid = current["pid"]
        existing = store.get(pid, "appointments", appt_id)
        if not existing:
            raise HTTPException(404, "No such appointment.")
        store.delete(pid, "appointments", appt_id)
        care.audit(ctx, pid, current["member"], "appointment removed", f"{existing['doctor']} {existing['when']}")
        return {"ok": True}

    # ---------- care notes ----------

    @router.get("/api/notes")
    def list_notes(current: dict = Depends(allow(*READERS))) -> list[dict]:
        return store.list(current["pid"], "notes", field="at", limit=100, newest_first=True)

    @router.post("/api/notes", status_code=201)
    def add_note(body: NoteIn, current: dict = Depends(allow(*CAREGIVERS))) -> dict:
        if not body.text and not body.tags:
            raise HTTPException(422, "Write a note or pick at least one tag.")
        now = care.local_now(current["profile"], ctx.clock())
        tags = list(body.tags) or ctx.summariser.suggest_tags(body.text)
        doc = {
            "id": security.new_id("n"),
            "at": now.isoformat(),
            "date": now.date().isoformat(),
            "text": body.text,
            "tags": tags,
            "by_name": current["member"]["name"],
            "by_role": current["member"]["role"],
        }
        store.put(current["pid"], "notes", doc["id"], doc)
        return doc

    # ---------- people, profile ----------

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
            "passcode_hash": passcode_hash_for(pid, body.passcode),
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
            existing["passcode_hash"] = passcode_hash_for(pid, body.passcode, skip_id=member_id)
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

    # ---------- summary, doctor request, history ----------

    @router.get("/api/summary")
    def summary(days: int = 14, write: bool = True, current: dict = Depends(allow(*READERS))) -> dict:
        """With write=false the facts come back at once, phrased by the template; the
        page shows them, then asks again with write=true for Gemini's wording."""
        if days not in (7, 14, 30):
            raise HTTPException(422, "Choose 7, 14 or 30 days.")
        facts = care.period_facts(ctx, current["pid"], current["profile"], days)
        template = care.period_template(facts)
        written = (
            ctx.summariser.write("the doctor and the family", facts, template)
            if write
            else {"text": template, "source": "template"}
        )
        notes = store.list(current["pid"], "notes", field="date", lo=facts["from"], hi=facts["to"])
        return {
            "facts": facts,
            "summary": written,
            "timeline": care.day_timeline(ctx, current["pid"], current["profile"], facts["from"], facts["to"]),
            "notes": sorted(notes, key=lambda n: n["at"], reverse=True)[:30],
        }

    @router.post("/api/doctor-request")
    def doctor_request(body: DoctorRequestIn, current: dict = Depends(allow(*CAREGIVERS))) -> dict:
        pid, profile, member = current["pid"], current["profile"], current["member"]
        contacts = profile.get("contacts", {})
        doctors = [
            {"name": m["name"], "email": m["email"]}
            for m in store.list(pid, "members")
            if m["role"] == "doctor" and m.get("email")
        ]
        if contacts.get("doctor_email"):
            doctors.append({"name": contacts.get("doctor_name") or "Doctor", "email": contacts["doctor_email"]})
        if not doctors:
            raise HTTPException(409, "Save the doctor's email under People first.")
        today_view = care.today_facts(ctx, pid, profile)
        meds = [m for m in store.list(pid, "medicines") if m.get("active", True)]
        notes = store.list(pid, "notes", field="at", limit=5, newest_first=True)
        facts = {
            "kind": body.kind,
            "by": f"{member['name']} ({member['role']})",
            "message": body.message,
            "phone": member.get("phone", ""),
            "medicines": "; ".join(
                f"{m['name']} {m.get('dose', '')} at {', '.join(s['time'] for s in m['slots'])}" for m in meds
            ),
            "today": care.today_template(today_view),
            "notes": "; ".join(f"{n['date']} {', '.join(n['tags'])} {n['text']}".strip() for n in notes),
        }
        key = f"doctor_{ctx.clock().strftime('%Y%m%dT%H%M')}"
        sent = notify.deliver(ctx, pid, profile, key, "doctor_request", doctors, facts)
        if sent is None:
            raise HTTPException(429, "A request was just sent. Please wait a minute.")
        care.audit(ctx, pid, member, "doctor request", body.kind)
        return {
            "ok": True,
            "to": [d["name"] for d in doctors],
            "delivered": sent["delivered"],
            "detail": sent["detail"],
        }

    @router.get("/api/outbox")
    def outbox(current: dict = Depends(allow("family"))) -> list[dict]:
        return store.list(current["pid"], "outbox", field="created_at", limit=60, newest_first=True)

    @router.get("/api/audit")
    def audit_log(current: dict = Depends(allow("family"))) -> list[dict]:
        return store.list(current["pid"], "audit", field="at", limit=60, newest_first=True)

    # ---------- scheduled work ----------

    @router.post("/tasks/tick")
    def tick(request: Request) -> dict:
        """Called by Cloud Scheduler every five minutes with a shared secret."""
        expected = ctx.settings.tick_token
        given = request.headers.get("x-tick-token", "")
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            raise HTTPException(403, "Not allowed.")
        return notify.run_tick(ctx)

    return router
