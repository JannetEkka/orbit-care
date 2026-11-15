"""Turns planned notifications into emails, exactly once each.

`run_tick` is what Cloud Scheduler triggers every few minutes. Each notification
has a stable key; the outbox entry is created only if that key is new, so a
repeated or overlapping tick can never send the same email twice.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from . import care, rules
from .care import Ctx

log = logging.getLogger("orbit.notify")
DEMO_LIFETIME = timedelta(hours=24)


def render(kind: str, facts: dict, elder: str, base_url: str) -> tuple[str, str]:
    """Subject and plain-text body for one notification."""
    f = facts
    medicine = " ".join(part for part in (f.get("medicine", ""), f.get("dose", "")) if part)
    if kind == "upcoming":
        subject = f"{elder}: {medicine} is due at {f['time']}"
        body = f"{medicine} for {elder} is due at {f['time']}."
        if f.get("instructions"):
            body += f"\nHow to give it: {f['instructions']}"
        body += "\nPlease mark it as given in Orbit once it is done."
    elif kind == "missed":
        subject = f"{elder}: {medicine} at {f['time']} is not marked as given"
        body = (
            f"The {f['time']} dose of {medicine} for {elder} has not been marked as given.\n"
            "If it was given, please mark it in Orbit. If it was skipped, record why."
        )
    elif kind == "escalated":
        subject = f"Missed dose: {elder} has not had {medicine} ({f['time']})"
        body = (
            f"The {f['time']} dose of {medicine} for {elder} is still not marked as given, "
            "and the person responsible has already been reminded.\n"
            "Please check with whoever is at home."
        )
    elif kind in {"appointment_week", "appointment_tomorrow"}:
        lead = "Tomorrow" if kind == "appointment_tomorrow" else "This week"
        subject = f"{lead}: {elder} sees {f['doctor']} on {f['when']}"
        body = f"{elder} has an appointment with {f['doctor']} on {f['when']}."
        if f.get("purpose"):
            body += f"\nFor: {f['purpose']}"
        body += f"\nGoing with {elder}: {f['accompany'] or 'nobody is assigned yet'}."
        if f.get("clinic_phone"):
            body += f"\nClinic: {f['clinic_phone']}"
    elif kind == "checkup_due":
        state = "is overdue" if f.get("overdue") else "is due"
        subject = f"{elder}: regular checkup with {f['doctor']} {state}, nothing is booked"
        body = (
            f"{elder}'s regular checkup with {f['doctor']} {state} on {f['next_due']} "
            f"(last visit {f['last_visit']}), and no appointment is booked."
        )
        if f.get("clinic_phone"):
            body += f"\nCall the clinic to book: {f['clinic_phone']}"
    elif kind == "refill":
        subject = f"{elder}: {f['name']} runs out in about {f['days_left']} days"
        body = (
            f"There are {f['stock']} of {f['name']} left for {elder}, about {f['days_left']} "
            "days at the current schedule.\nOpen Orbit for the buy and chemist shortcuts."
        )
    elif kind == "help":
        subject = f"HELP pressed at {elder}'s bedside ({f['time']})"
        body = (
            f"The Help button on {elder}'s bedside screen was pressed at {f['time']} "
            f"by {f['by']}.\nPlease call or go to {elder} now."
        )
    elif kind == "doctor_request":
        what = "a home visit" if f["kind"] == "visit" else "a call back"
        subject = f"Request for {what}: {elder}"
        body = (
            f"{f['by']} is asking for {what} for {elder}.\n"
            + (f"Message: {f['message']}\n" if f.get("message") else "")
            + f"\nCurrent medicines: {f['medicines'] or 'none recorded'}\n"
            f"Today: {f['today']}\n"
            f"Recent care notes: {f['notes'] or 'none'}\n" + (f"Call back on: {f['phone']}\n" if f.get("phone") else "")
        )
    elif kind == "digest":
        subject = f"{elder}'s day: {f['date']}"
        body = f["text"]
    else:
        raise ValueError(f"Unknown notification kind: {kind}")
    if base_url:
        body += f"\n\nOpen Orbit: {base_url}"
    return subject, body


def deliver(
    ctx: Ctx,
    pid: str,
    profile: dict,
    key: str,
    kind: str,
    recipients: list[dict],
    facts: dict,
) -> dict | None:
    """Create the outbox entry for `key` and send it. None if it already exists."""
    now = ctx.clock()
    subject, body = render(kind, facts, profile["elder_name"], ctx.settings.base_url)
    doc = {
        "id": key,
        "kind": kind,
        "to": [r["email"] for r in recipients],
        "to_names": [r["name"] for r in recipients],
        "subject": subject,
        "body": body,
        "created_at": now.isoformat(),
        "delivered": False,
        "detail": "",
    }
    if not ctx.store.create_if_absent(pid, "outbox", key, doc):
        return None
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    sent_today = len(ctx.store.list(pid, "outbox", field="created_at", lo=day_start))
    if profile.get("demo"):
        doc["detail"] = "Demo orbit: shown here, not sent to a real inbox."
    elif sent_today > ctx.settings.daily_email_cap:
        doc["detail"] = "Daily email limit reached; kept here only."
    else:
        doc["delivered"], doc["detail"] = ctx.mailer.send(doc["to"], subject, body)
    ctx.store.put(pid, "outbox", key, doc)
    return doc


def tick_profile(ctx: Ctx, pid: str) -> int:
    """Send whatever is due for one orbit. Returns how many emails were created."""
    profile = ctx.store.get_profile(pid)
    if not profile:
        return 0
    utc_now = ctx.clock()
    if profile.get("demo") and datetime.fromisoformat(profile["created_at"]) < utc_now - DEMO_LIFETIME:
        ctx.store.delete_profile(pid)
        return 0
    now = care.local_now(profile, utc_now)
    members = ctx.store.list(pid, "members")
    meds = ctx.store.list(pid, "medicines")
    events = care.load_events(ctx.store, pid, now.date() - timedelta(days=1), now.date())
    appointments = ctx.store.list(pid, "appointments")
    by_id = {m["id"]: m for m in members}
    created = 0
    for item in rules.plan_notifications(profile, members, meds, events, appointments, now):
        if ctx.store.get(pid, "outbox", item["key"]):
            continue
        facts = item["facts"]
        if item["kind"] == "digest":
            today = care.today_facts(ctx, pid, profile)
            written = ctx.summariser.write("the family", today, care.today_template(today))
            facts = {"date": today["date"], "text": written["text"]}
        recipients = [by_id[m] for m in item["to"] if m in by_id]
        if deliver(ctx, pid, profile, item["key"], item["kind"], recipients, facts):
            created += 1
    return created


def run_tick(ctx: Ctx) -> dict:
    """Run the reminder rules for every orbit. One failing orbit never stops the rest."""
    created = failed = 0
    profile_ids = ctx.store.list_profile_ids()
    for pid in profile_ids:
        try:
            created += tick_profile(ctx, pid)
        except Exception:  # noqa: BLE001 - isolate one orbit's failure from the others
            failed += 1
            log.exception("Tick failed for one orbit")
    return {"orbits": len(profile_ids), "emails_created": created, "failed": failed}
