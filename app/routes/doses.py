"""Today's doses, marking them, how the elder feels, the bedside screen and Help."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from .. import care, notify, rules
from ..models import FeelingIn, MarkIn
from .deps import CAREGIVERS, EVERYONE, READERS, Deps

HELP_COOLDOWN = timedelta(seconds=60)


def register(router: APIRouter, d: Deps) -> None:
    ctx, store, allow, public_member = d.ctx, d.store, d.allow, d.public_member

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
