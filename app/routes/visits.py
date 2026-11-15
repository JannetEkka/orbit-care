"""Doctor visits and regular checkups."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import care, security
from ..models import AppointmentIn
from .deps import CAREGIVERS, READERS, Deps


def register(router: APIRouter, d: Deps) -> None:
    ctx, store, allow, check_limit, check_member_refs = d.ctx, d.store, d.allow, d.check_limit, d.check_member_refs

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
