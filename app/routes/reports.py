"""Care notes, the doctor's brief, requests to the doctor, sent emails and history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import care, notify, security
from ..models import DoctorRequestIn, NoteIn
from .deps import CAREGIVERS, READERS, Deps


def register(router: APIRouter, d: Deps) -> None:
    ctx, store, allow = d.ctx, d.store, d.allow

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
