"""Adding, changing and stopping medicines."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import care, rules, security
from ..models import MedicineIn
from .deps import CAREGIVERS, READERS, Deps


def register(router: APIRouter, d: Deps) -> None:
    ctx, store, allow, check_limit, check_member_refs = d.ctx, d.store, d.allow, d.check_limit, d.check_member_refs

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
