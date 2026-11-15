"""Reads one orbit's state from storage and turns it into facts.

The facts built here are the only thing the model ever sees, and the plain
templates here are what is shown when the model is unavailable or fails its check.
"""

from __future__ import annotations

import secrets
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import rules
from .config import Settings
from .mailer import Mailer
from .store import Store
from .summary import Summariser


@dataclass
class Ctx:
    """Everything a request or a scheduled tick needs."""

    settings: Settings
    store: Store
    mailer: Mailer
    summariser: Summariser
    clock: Callable[[], datetime]


def local_now(profile: dict, utc_now: datetime) -> datetime:
    """`utc_now` as a naive datetime in the elder's own time zone."""
    zone = ZoneInfo(rules.settings_of(profile)["timezone"])
    return utc_now.astimezone(zone).replace(tzinfo=None, microsecond=0)


def load_events(store: Store, pid: str, start: date, end: date) -> dict[str, dict]:
    docs = store.list(pid, "doses", field="date", lo=start.isoformat(), hi=end.isoformat())
    return {doc["key"]: doc for doc in docs}


def audit(ctx: Ctx, pid: str, who: dict, action: str, detail: str) -> None:
    """Record who changed what, so the family can always see the history."""
    now = ctx.clock()
    doc_id = f"a_{now.strftime('%Y%m%d%H%M%S%f')}_{secrets.token_hex(3)}"
    ctx.store.put(
        pid,
        "audit",
        doc_id,
        {
            "id": doc_id,
            "at": now.isoformat(),
            "by_name": who.get("name", ""),
            "by_role": who.get("role", ""),
            "action": action,
            "detail": detail[:200],
        },
    )


def period_facts(ctx: Ctx, pid: str, profile: dict, days: int) -> dict:
    """Computed facts for the last `days` days: adherence, notes, feelings."""
    now = local_now(profile, ctx.clock())
    end, start = now.date(), now.date() - timedelta(days=days - 1)
    created = profile.get("created_on")
    if created and date.fromisoformat(created) > start:
        start = date.fromisoformat(created)
    meds = ctx.store.list(pid, "medicines")
    events = load_events(ctx.store, pid, start, end)
    stats = rules.adherence(meds, events, start, end, now, rules.settings_of(profile))
    notes = ctx.store.list(pid, "notes", field="date", lo=start.isoformat(), hi=end.isoformat())
    feelings = ctx.store.list(pid, "feelings", field="date", lo=start.isoformat(), hi=end.isoformat())
    tags = Counter(tag for note in notes for tag in note.get("tags", []))
    moods = Counter(f["value"] for f in feelings)
    parts = {part: row["percent"] for part, row in stats["by_part_of_day"].items() if row["percent"] is not None}
    weakest = min(parts, key=parts.get) if len(parts) > 1 else None
    return {
        "elder": profile["elder_name"],
        "days": (end - start).days + 1,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "adherence": stats,
        "weakest_part_of_day": weakest,
        "care_notes": dict(tags.most_common()),
        "feeling_good_days": moods.get("good", 0),
        "feeling_not_good_days": moods.get("not_good", 0),
        "refill_soon": [w["name"] for w in rules.refill_warnings(meds, rules.settings_of(profile))],
    }


def period_template(facts: dict) -> str:
    """The summary in fixed words, used when the model is off or fails its check."""
    overall = facts["adherence"]["overall"]
    name = facts["elder"]
    if not overall["scheduled"]:
        return f"No doses have come due for {name} in this period yet."
    lines = [
        f"Over the last {facts['days']} days, {name} was given {overall['given']} of "
        f"{overall['scheduled']} scheduled doses ({overall['percent']}%). "
        f"Missed: {overall['missed']}. Skipped: {overall['skipped']}."
    ]
    weakest = facts.get("weakest_part_of_day")
    if weakest:
        percent = facts["adherence"]["by_part_of_day"][weakest]["percent"]
        lines.append(f"{weakest.capitalize()} doses were the weakest, at {percent}%.")
    if facts["care_notes"]:
        noted = ", ".join(f"{tag.replace('_', ' ')} {count}" for tag, count in facts["care_notes"].items())
        lines.append(f"Care notes recorded: {noted}.")
    if facts["feeling_good_days"] or facts["feeling_not_good_days"]:
        lines.append(
            f"{name} answered 'good' on {facts['feeling_good_days']} days and "
            f"'not good' on {facts['feeling_not_good_days']}."
        )
    if facts["refill_soon"]:
        lines.append("Running low: " + ", ".join(facts["refill_soon"]) + ".")
    return " ".join(lines)


def today_facts(ctx: Ctx, pid: str, profile: dict) -> dict:
    """Computed facts about today, for the evening update to the family."""
    now = local_now(profile, ctx.clock())
    today = now.date()
    settings = rules.settings_of(profile)
    meds = ctx.store.list(pid, "medicines")
    events = load_events(ctx.store, pid, today, today)
    view = rules.day_view(meds, events, today, now, settings)
    notes = ctx.store.list(pid, "notes", field="date", lo=today.isoformat(), hi=today.isoformat())
    feeling = ctx.store.get(pid, "feelings", today.isoformat())
    upcoming = sorted(
        (a for a in ctx.store.list(pid, "appointments") if a["when"] > now.isoformat()),
        key=lambda a: a["when"],
    )
    return {
        "elder": profile["elder_name"],
        "date": today.strftime("%A %d %B"),
        "doses_given": sum(1 for d in view if d["state"] == "given"),
        "doses_scheduled": len(view),
        "missed": [f"{d['name']} at {d['time']}" for d in view if d["state"] == "missed"],
        "skipped": [f"{d['name']} at {d['time']}" for d in view if d["state"] == "skipped"],
        "care_notes": sorted({tag.replace("_", " ") for n in notes for tag in n.get("tags", [])}),
        "feeling": {"good": "good", "not_good": "not good"}.get((feeling or {}).get("value"), "not answered"),
        "next_appointment": (
            f"{upcoming[0]['doctor']} on {datetime.fromisoformat(upcoming[0]['when']).strftime('%A %d %B at %H:%M')}"
            if upcoming
            else ""
        ),
        "refill_soon": [w["name"] for w in rules.refill_warnings(meds, settings)],
    }


def today_template(facts: dict) -> str:
    lines = [
        f"{facts['date']}: {facts['elder']} was given {facts['doses_given']} of "
        f"{facts['doses_scheduled']} doses scheduled today."
    ]
    if facts["missed"]:
        lines.append("Missed: " + "; ".join(facts["missed"]) + ".")
    if facts["skipped"]:
        lines.append("Skipped: " + "; ".join(facts["skipped"]) + ".")
    if facts["care_notes"]:
        lines.append("Care notes today: " + ", ".join(facts["care_notes"]) + ".")
    lines.append(f"Asked how the day felt: {facts['feeling']}.")
    if facts["next_appointment"]:
        lines.append(f"Next appointment: {facts['next_appointment']}.")
    if facts["refill_soon"]:
        lines.append("Running low: " + ", ".join(facts["refill_soon"]) + ".")
    return " ".join(lines)


def day_timeline(ctx: Ctx, pid: str, profile: dict, start_text: str, end_text: str) -> list[dict]:
    """One row per day, newest first: each dose's state next to that day's symptoms and mood."""
    now = local_now(profile, ctx.clock())
    start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
    settings = rules.settings_of(profile)
    meds = ctx.store.list(pid, "medicines")
    events = load_events(ctx.store, pid, start, end)
    notes = ctx.store.list(pid, "notes", field="date", lo=start_text, hi=end_text)
    feelings = {
        f["date"]: f["value"] for f in ctx.store.list(pid, "feelings", field="date", lo=start_text, hi=end_text)
    }
    rows = []
    day = end
    while day >= start:
        view = rules.day_view(meds, events, day, now, settings)
        text = day.isoformat()
        rows.append(
            {
                "date": text,
                "doses": [{"time": d["time"], "name": d["name"], "state": d["state"]} for d in view],
                "tags": sorted({t for n in notes if n["date"] == text for t in n.get("tags", [])}),
                "feeling": feelings.get(text),
            }
        )
        day -= timedelta(days=1)
    return rows
