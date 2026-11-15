"""Fixed rules: what is due, what was missed, who is told, how adherence is counted.

Everything here is a pure function of its arguments (no clock, no storage, no
model), so each rule is easy to test and behaves the same every time. Times are
naive datetimes in the elder's own time zone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

DEFAULT_SETTINGS = {
    "timezone": "Asia/Kolkata",
    "upcoming_lead_min": 15,
    "missed_after_min": 30,
    "escalate_after_min": 60,
    "refill_warn_days": 5,
    "digest_hour": 20,
}
PARTS_OF_DAY = ("morning", "afternoon", "evening", "night")
NOTIFY_LOOKBACK = timedelta(hours=12)


@dataclass(frozen=True)
class Dose:
    """One scheduled dose of one medicine on one day."""

    key: str
    med_id: str
    name: str
    dose: str
    instructions: str
    colour: str
    time: str
    due_at: datetime
    giver_id: str | None


def settings_of(profile: dict) -> dict:
    return {**DEFAULT_SETTINGS, **(profile.get("settings") or {})}


def dose_key(med_id: str, day: date, hhmm: str) -> str:
    return f"{med_id}_{day.isoformat()}_{hhmm.replace(':', '')}"


def part_of_day(hhmm: str) -> str:
    hour = int(hhmm[:2])
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def med_active_on(med: dict, day: date) -> bool:
    if not med.get("active", True):
        return False
    start, end = med.get("start_date"), med.get("end_date")
    if start and day < date.fromisoformat(start):
        return False
    return not (end and day > date.fromisoformat(end))


def doses_for_day(meds: list[dict], day: date) -> list[Dose]:
    doses = []
    for med in meds:
        if not med_active_on(med, day):
            continue
        for slot in med.get("slots", []):
            hhmm = slot["time"]
            due_at = datetime(day.year, day.month, day.day, int(hhmm[:2]), int(hhmm[3:]))
            doses.append(
                Dose(
                    key=dose_key(med["id"], day, hhmm),
                    med_id=med["id"],
                    name=med["name"],
                    dose=med.get("dose", ""),
                    instructions=med.get("instructions", ""),
                    colour=med.get("colour", "white"),
                    time=hhmm,
                    due_at=due_at,
                    giver_id=slot.get("giver_id"),
                )
            )
    return sorted(doses, key=lambda d: (d.due_at, d.name))


def dose_state(dose: Dose, event: dict | None, now: datetime, settings: dict) -> str:
    """given | skipped | upcoming | due | missed. A recorded event always wins."""
    if event and event.get("status") in {"given", "skipped"}:
        return event["status"]
    if now < dose.due_at:
        return "upcoming"
    if now < dose.due_at + timedelta(minutes=settings["missed_after_min"]):
        return "due"
    return "missed"


def day_view(meds: list[dict], events: dict[str, dict], day: date, now: datetime, settings: dict) -> list[dict]:
    """The day's doses with their state, ready to show."""
    view = []
    for dose in doses_for_day(meds, day):
        event = events.get(dose.key)
        view.append(
            {
                "key": dose.key,
                "med_id": dose.med_id,
                "name": dose.name,
                "dose": dose.dose,
                "instructions": dose.instructions,
                "colour": dose.colour,
                "time": dose.time,
                "giver_id": dose.giver_id,
                "state": dose_state(dose, event, now, settings),
                "by_name": (event or {}).get("by_name"),
                "at": (event or {}).get("at"),
                "reason": (event or {}).get("reason", ""),
            }
        )
    return view


def adherence(
    meds: list[dict],
    events: dict[str, dict],
    start: date,
    end: date,
    now: datetime,
    settings: dict,
) -> dict:
    """Count resolved doses from `start` to `end` inclusive.

    A dose counts once it is given, skipped or missed. Doses still upcoming or
    within their grace period are left out, so today's figure is never unfair.
    """

    def blank() -> dict:
        return {"given": 0, "skipped": 0, "missed": 0, "scheduled": 0, "percent": None}

    overall = blank()
    by_med: dict[str, dict] = {}
    by_part = {part: blank() for part in PARTS_OF_DAY}
    day = start
    while day <= end:
        for dose in doses_for_day(meds, day):
            state = dose_state(dose, events.get(dose.key), now, settings)
            if state not in {"given", "skipped", "missed"}:
                continue
            med_row = by_med.setdefault(dose.med_id, {"name": dose.name, **blank()})
            for row in (overall, med_row, by_part[part_of_day(dose.time)]):
                row[state] += 1
                row["scheduled"] += 1
        day += timedelta(days=1)
    for row in (overall, *by_med.values(), *by_part.values()):
        if row["scheduled"]:
            row["percent"] = round(100 * row["given"] / row["scheduled"])
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "overall": overall,
        "by_medicine": sorted(by_med.values(), key=lambda r: r["name"].lower()),
        "by_part_of_day": by_part,
    }


def days_of_stock(med: dict) -> float | None:
    """How many days the tablets in hand will last, or None if not tracked."""
    stock = med.get("stock")
    per_day = len(med.get("slots", [])) * int(med.get("per_dose", 1))
    if stock is None or per_day == 0 or not med.get("active", True):
        return None
    return stock / per_day


def refill_warnings(meds: list[dict], settings: dict) -> list[dict]:
    warnings = []
    for med in meds:
        left = days_of_stock(med)
        if left is not None and left <= settings["refill_warn_days"]:
            warnings.append(
                {
                    "med_id": med["id"],
                    "name": med["name"],
                    "stock": med["stock"],
                    "days_left": int(left),
                    "stock_set_on": med.get("stock_set_on", ""),
                }
            )
    return warnings


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def checkups_due(appointments: list[dict], now: datetime, window_days: int = 7) -> list[dict]:
    """Regular checkups that are due soon with no next visit booked.

    For each doctor, take the latest visit that has a repeat interval. If it has
    already happened, nothing later is booked with that doctor, and the next one
    falls within `window_days`, the checkup is due.
    """
    by_doctor: dict[str, list[dict]] = {}
    for appt in appointments:
        by_doctor.setdefault(slug(appt["doctor"]), []).append(appt)
    due = []
    for doctor_slug, visits in by_doctor.items():
        visits.sort(key=lambda a: a["when"])
        latest = visits[-1]
        repeat = latest.get("repeat_days")
        when = datetime.fromisoformat(latest["when"])
        if not repeat or when > now:
            continue
        next_due = when.date() + timedelta(days=int(repeat))
        if now.date() >= next_due - timedelta(days=window_days):
            due.append(
                {
                    "doctor": latest["doctor"],
                    "doctor_slug": doctor_slug,
                    "clinic_phone": latest.get("clinic_phone", ""),
                    "next_due": next_due.isoformat(),
                    "last_visit": when.date().isoformat(),
                    "overdue": now.date() > next_due,
                }
            )
    return sorted(due, key=lambda c: c["next_due"])


def _with_email(members: list[dict], roles: set[str]) -> list[str]:
    return [m["id"] for m in members if m.get("role") in roles and m.get("email")]


def plan_notifications(
    profile: dict,
    members: list[dict],
    meds: list[dict],
    events: dict[str, dict],
    appointments: list[dict],
    now: datetime,
) -> list[dict]:
    """Every email that should exist by `now`.

    Each one has a stable `key`, so sending is idempotent: the caller creates the
    outbox entry only if that key is new. Running this twice sends nothing twice.
    """
    settings = settings_of(profile)
    family = _with_email(members, {"family"})
    circle = _with_email(members, {"family", "caretaker"})
    have_email = {m["id"] for m in members if m.get("email")}
    plan: list[dict] = []

    for day in (now.date() - timedelta(days=1), now.date()):
        for dose in doses_for_day(meds, day):
            if dose.due_at < now - NOTIFY_LOOKBACK:
                continue
            if dose_state(dose, events.get(dose.key), now, settings) in {"given", "skipped"}:
                continue
            giver = [dose.giver_id] if dose.giver_id in have_email else family
            facts = {
                "medicine": dose.name,
                "dose": dose.dose,
                "time": dose.time,
                "instructions": dose.instructions,
            }
            lead = dose.due_at - timedelta(minutes=settings["upcoming_lead_min"])
            missed_at = dose.due_at + timedelta(minutes=settings["missed_after_min"])
            escalate_at = dose.due_at + timedelta(minutes=settings["escalate_after_min"])
            if lead <= now < dose.due_at:
                plan.append({"key": f"upcoming_{dose.key}", "kind": "upcoming", "to": giver, "facts": facts})
            if now >= missed_at:
                plan.append({"key": f"missed_{dose.key}", "kind": "missed", "to": giver, "facts": facts})
            if now >= escalate_at:
                rest = [m for m in circle if m not in giver] or circle
                plan.append({"key": f"escalated_{dose.key}", "kind": "escalated", "to": rest, "facts": facts})

    names = {m["id"]: m["name"] for m in members}
    for appt in appointments:
        when = datetime.fromisoformat(appt["when"])
        if when <= now:
            continue
        to = sorted(set(family) | ({appt.get("accompany_id")} & have_email))
        facts = {
            "doctor": appt["doctor"],
            "purpose": appt.get("purpose", ""),
            "when": when.strftime("%A %d %B, %H:%M"),
            "accompany": names.get(appt.get("accompany_id"), ""),
            "clinic_phone": appt.get("clinic_phone", ""),
        }
        stamp = f"{appt['id']}_{when.strftime('%Y%m%dT%H%M')}"
        if when - now <= timedelta(days=1):
            plan.append({"key": f"appt_day_{stamp}", "kind": "appointment_tomorrow", "to": to, "facts": facts})
        elif when - now <= timedelta(days=7):
            plan.append({"key": f"appt_week_{stamp}", "kind": "appointment_week", "to": to, "facts": facts})

    for checkup in checkups_due(appointments, now):
        plan.append(
            {
                "key": f"checkup_{checkup['doctor_slug']}_{checkup['next_due']}",
                "kind": "checkup_due",
                "to": family,
                "facts": checkup,
            }
        )

    for warning in refill_warnings(meds, settings):
        plan.append(
            {
                "key": f"refill_{warning['med_id']}_{warning['stock_set_on']}",
                "kind": "refill",
                "to": family,
                "facts": warning,
            }
        )

    if now.hour >= settings["digest_hour"]:
        to = [m["id"] for m in members if m["id"] in family and m.get("digest", True)]
        plan.append({"key": f"digest_{now.date().isoformat()}", "kind": "digest", "to": to, "facts": {}})

    return [item for item in plan if item["to"]]
