"""A sample orbit so a visitor can see the product with a week of history.

Every demo orbit gets its own random code and random passcodes, shown once to
the visitor who created it. Nothing here is a fixed credential. Demo orbits never
send real email and are deleted after 24 hours.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import care, rules, security
from .care import Ctx

# (name, dose, instructions, colour, [(time, giver)], stock)
MEDICINES = (
    (
        "Levodopa-Carbidopa",
        "100/25 mg",
        "30 minutes before food",
        "yellow",
        (("08:00", "wife"), ("13:00", "nurse"), ("18:00", "nurse"), ("22:00", "wife")),
        18,
    ),
    ("Amlodipine", "5 mg", "After breakfast", "white", (("09:00", "wife"),), 22),
    ("Atorvastatin", "10 mg", "At bedtime", "pink", (("22:00", "wife"),), 4),
    ("Pantoprazole", "40 mg", "Before breakfast, empty stomach", "orange", (("07:30", "wife"),), 30),
)
# Doses left unmarked (missed) or skipped in the seeded week: (days ago, time, medicine index).
MISSED = {(1, "18:00", 0), (2, "22:00", 0), (2, "22:00", 2), (4, "18:00", 0), (5, "22:00", 2), (6, "13:00", 0)}
SKIPPED = {(3, "08:00", 0): "Vomited after breakfast"}
NOTES = (
    (0, "09:20", ["tremor"], "Hands shaking more than usual before the morning dose.", "nurse"),
    (1, "19:10", ["confusion", "sleepy"], "Did not recognise the nurse for a few minutes after his nap.", "nurse"),
    (3, "08:40", ["nausea", "not_eating"], "Vomited after breakfast, ate very little.", "wife"),
    (4, "16:30", ["calm"], "Good afternoon. Listened to old songs and smiled.", "wife"),
    (6, "21:00", ["fall"], "Slipped getting out of the chair. No injury seen.", "nurse"),
)
FEELINGS = {1: "not_good", 2: "good", 3: "not_good", 4: "good", 5: "good", 6: "good"}


def seed_demo(ctx: Ctx) -> tuple[str, dict, dict]:
    """Create one demo orbit. Returns (orbit code, passcodes by role, family member)."""
    store = ctx.store
    utc_now = ctx.clock()
    pid = security.new_orbit_code()
    profile = {
        "id": pid,
        "elder_name": "Mr. Thomas",
        "demo": True,
        "created_at": utc_now.isoformat(),
        "about": {
            "address_as": "Papa",
            "likes": "Old film songs, tea with two biscuits at four, the balcony chair.",
            "calms": "Holding his hand and speaking slowly. His daughter's voice on the phone.",
            "notes": "Parkinson's with brain microbleeds. Speech is slow; give him time to answer.",
        },
        "contacts": {
            "chemist_name": "Neighbourhood chemist",
            "chemist_phone": "",
            "hospital_name": "",
            "hospital_phone": "",
            "doctor_name": "Dr. Rao (neurologist)",
            "doctor_phone": "",
            "doctor_email": "",
            "ambulance_phone": "108",
        },
        "settings": dict(rules.DEFAULT_SETTINGS),
    }
    now = care.local_now(profile, utc_now)
    today = now.date()
    profile["created_on"] = (today - timedelta(days=6)).isoformat()
    store.create_profile(pid, profile)

    people = {
        "wife": ("Mary (wife)", "family", "mary@example.com"),
        "son": ("Arun (son)", "family", "arun@example.com"),
        "nurse": ("Sister Latha (nurse)", "caretaker", "latha@example.com"),
        "doctor": ("Dr. Rao", "doctor", "rao@example.com"),
        "bedside": ("Bedside screen", "elder", ""),
    }
    passcodes, members = {}, {}
    for slot, (name, role, email) in people.items():
        passcode = security.new_passcode()
        while passcode in passcodes.values():
            passcode = security.new_passcode()
        passcodes[slot] = passcode
        members[slot] = {
            "id": security.new_id("m"),
            "name": name,
            "role": role,
            "email": email,
            "phone": "",
            "digest": True,
            "passcode_hash": security.hash_passcode(passcode),
        }
        store.put(pid, "members", members[slot]["id"], members[slot])

    # One dose is due right now, so a visitor sees the bedside button straight away.
    due_now = (now - timedelta(minutes=5)).strftime("%H:%M")
    medicines = MEDICINES + (("Vitamin D3", "1000 IU", "With water", "blue", ((due_now, "nurse"),), 25),)
    meds = []
    for name, dose, instructions, colour, slots, stock in medicines:
        med = {
            "id": security.new_id("med"),
            "name": name,
            "dose": dose,
            "instructions": instructions,
            "colour": colour,
            "slots": [{"time": t, "giver_id": members[g]["id"]} for t, g in slots],
            "per_dose": 1,
            "stock": stock,
            "stock_set_on": today.isoformat(),
            "start_date": today.isoformat() if name == "Vitamin D3" else profile["created_on"],
            "active": True,
        }
        meds.append(med)
        store.put(pid, "medicines", med["id"], med)

    for days_ago in range(6, -1, -1):
        day = today - timedelta(days=days_ago)
        for dose in rules.doses_for_day(meds, day):
            index = next(i for i, m in enumerate(meds) if m["id"] == dose.med_id)
            if dose.due_at > now - timedelta(minutes=20) or (days_ago, dose.time, index) in MISSED:
                continue
            reason = SKIPPED.get((days_ago, dose.time, index))
            giver = next(m for m in members.values() if m["id"] == dose.giver_id)
            store.put(
                pid,
                "doses",
                dose.key,
                {
                    "key": dose.key,
                    "med_id": dose.med_id,
                    "date": day.isoformat(),
                    "time": dose.time,
                    "status": "skipped" if reason else "given",
                    "reason": reason or "",
                    "by_id": giver["id"],
                    "by_name": giver["name"],
                    "by_role": giver["role"],
                    "at": (dose.due_at + timedelta(minutes=7)).isoformat(),
                },
            )
        if days_ago in FEELINGS:
            store.put(
                pid,
                "feelings",
                day.isoformat(),
                {"date": day.isoformat(), "value": FEELINGS[days_ago], "by_role": "elder"},
            )

    for days_ago, hhmm, tags, text, who in NOTES:
        at = datetime.fromisoformat(f"{(today - timedelta(days=days_ago)).isoformat()}T{hhmm}:00")
        if at > now:
            continue
        note_id = security.new_id("n")
        store.put(
            pid,
            "notes",
            note_id,
            {
                "id": note_id,
                "at": at.isoformat(),
                "date": at.date().isoformat(),
                "text": text,
                "tags": tags,
                "by_name": members[who]["name"],
                "by_role": members[who]["role"],
            },
        )

    appointments = (
        ("Dr. Rao (neurologist)", "Review of tremor and night doses", now + timedelta(days=3, hours=2), "son", 90),
        ("Dr. Mehta (physician)", "Regular blood pressure checkup", now - timedelta(days=58), "wife", 60),
    )
    for doctor, purpose, when, who, repeat in appointments:
        appt_id = security.new_id("ap")
        store.put(
            pid,
            "appointments",
            appt_id,
            {
                "id": appt_id,
                "doctor": doctor,
                "purpose": purpose,
                "when": when.replace(minute=0, second=0, microsecond=0).isoformat(),
                "clinic_phone": "",
                "accompany_id": members[who]["id"],
                "repeat_days": repeat,
            },
        )

    care.audit(ctx, pid, members["wife"], "orbit created", "demo orbit with a sample week")
    return pid, passcodes, members["wife"]
