"""The fixed rules: dose states, adherence, refills, checkups and who is told."""

from datetime import date, datetime

from app import rules

SETTINGS = dict(rules.DEFAULT_SETTINGS)
MED = {
    "id": "med_aaaaaaaaaaaa",
    "name": "Levodopa",
    "dose": "100 mg",
    "slots": [{"time": "08:00", "giver_id": "m_nurse"}, {"time": "20:00", "giver_id": None}],
    "stock": 9,
    "per_dose": 1,
    "active": True,
}
MEMBERS = [
    {"id": "m_wife", "name": "Mary", "role": "family", "email": "mary@example.com"},
    {"id": "m_son", "name": "Arun", "role": "family", "email": "arun@example.com"},
    {"id": "m_nurse", "name": "Latha", "role": "caretaker", "email": "latha@example.com"},
    {"id": "m_doc", "name": "Dr Rao", "role": "doctor", "email": "rao@example.com"},
]
PROFILE = {"settings": SETTINGS}
DAY = date(2026, 11, 15)


def dose_at(hhmm: str) -> rules.Dose:
    return next(d for d in rules.doses_for_day([MED], DAY) if d.time == hhmm)


def test_dose_states_follow_the_clock():
    dose = dose_at("08:00")
    assert rules.dose_state(dose, None, datetime(2026, 11, 15, 7, 59), SETTINGS) == "upcoming"
    assert rules.dose_state(dose, None, datetime(2026, 11, 15, 8, 29), SETTINGS) == "due"
    assert rules.dose_state(dose, None, datetime(2026, 11, 15, 8, 30), SETTINGS) == "missed"


def test_a_recorded_event_always_wins():
    dose = dose_at("08:00")
    late = datetime(2026, 11, 15, 12, 0)
    assert rules.dose_state(dose, {"status": "given"}, late, SETTINGS) == "given"
    assert rules.dose_state(dose, {"status": "skipped"}, late, SETTINGS) == "skipped"


def test_medicine_outside_its_dates_has_no_doses():
    stopped = dict(MED, end_date="2026-11-14")
    future = dict(MED, start_date="2026-11-16")
    assert rules.doses_for_day([stopped], DAY) == []
    assert rules.doses_for_day([future], DAY) == []
    assert rules.doses_for_day([dict(MED, active=False)], DAY) == []


def test_adherence_counts_only_resolved_doses():
    events = {dose_at("08:00").key: {"status": "given"}}
    now = datetime(2026, 11, 15, 9, 0)  # 20:00 has not come yet
    stats = rules.adherence([MED], events, DAY, DAY, now, SETTINGS)
    assert stats["overall"] == {"given": 1, "skipped": 0, "missed": 0, "scheduled": 1, "percent": 100}
    assert stats["by_part_of_day"]["evening"]["scheduled"] == 0


def test_adherence_by_part_of_day_finds_the_weak_evening():
    events = {}
    for day in (date(2026, 11, 13), date(2026, 11, 14)):
        for dose in rules.doses_for_day([MED], day):
            if dose.time == "08:00":
                events[dose.key] = {"status": "given"}
    stats = rules.adherence([MED], events, date(2026, 11, 13), date(2026, 11, 14), datetime(2026, 11, 15, 9), SETTINGS)
    assert stats["by_part_of_day"]["morning"]["percent"] == 100
    assert stats["by_part_of_day"]["evening"]["percent"] == 0
    assert stats["overall"]["percent"] == 50


def test_refill_warning_uses_days_of_stock():
    assert rules.days_of_stock(MED) == 4.5
    warnings = rules.refill_warnings([MED], SETTINGS)
    assert warnings[0]["days_left"] == 4
    assert rules.refill_warnings([dict(MED, stock=40)], SETTINGS) == []
    assert rules.days_of_stock(dict(MED, stock=None)) is None


def test_checkup_due_only_when_nothing_is_booked():
    last = {"id": "ap_1", "doctor": "Dr. Mehta", "when": "2026-09-20T10:00:00", "repeat_days": 60}
    now = datetime(2026, 11, 15, 9, 0)  # next due 2026-11-19, within a week
    due = rules.checkups_due([last], now)
    assert due and due[0]["next_due"] == "2026-11-19" and not due[0]["overdue"]
    booked = {"id": "ap_2", "doctor": "Dr. Mehta", "when": "2026-11-19T10:00:00"}
    assert rules.checkups_due([last, booked], now) == []


def test_reminder_goes_to_the_giver_then_the_whole_family():
    events: dict = {}
    kinds = lambda now: {  # noqa: E731
        (n["kind"], tuple(n["to"]))
        for n in rules.plan_notifications(PROFILE, MEMBERS, [MED], events, [], now)
        if n["key"].endswith("0800")
    }
    assert ("upcoming", ("m_nurse",)) in kinds(datetime(2026, 11, 15, 7, 50))
    assert ("missed", ("m_nurse",)) in kinds(datetime(2026, 11, 15, 8, 35))
    escalated = kinds(datetime(2026, 11, 15, 9, 5))
    assert ("escalated", ("m_wife", "m_son")) in escalated


def test_doctors_are_never_sent_dose_reminders():
    plan = rules.plan_notifications(PROFILE, MEMBERS, [MED], {}, [], datetime(2026, 11, 15, 9, 5))
    assert all("m_doc" not in item["to"] for item in plan)


def test_a_given_dose_creates_no_missed_reminder():
    events = {dose_at("08:00").key: {"status": "given"}}
    plan = rules.plan_notifications(PROFILE, MEMBERS, [MED], events, [], datetime(2026, 11, 15, 9, 5))
    assert not [p for p in plan if p["key"].endswith("0800")]


def test_an_unassigned_dose_goes_to_the_family():
    plan = rules.plan_notifications(PROFILE, MEMBERS, [MED], {}, [], datetime(2026, 11, 15, 20, 31))
    missed = next(p for p in plan if p["kind"] == "missed" and p["key"].endswith("2000"))
    assert missed["to"] == ["m_wife", "m_son"]


def test_appointment_reminders_a_week_and_a_day_before():
    appt = {"id": "ap_x", "doctor": "Dr. Rao", "when": "2026-11-18T12:00:00", "accompany_id": "m_nurse"}
    week = rules.plan_notifications(PROFILE, MEMBERS, [], {}, [appt], datetime(2026, 11, 15, 9))
    assert [p["kind"] for p in week] == ["appointment_week"]
    assert set(week[0]["to"]) == {"m_wife", "m_son", "m_nurse"}
    day = rules.plan_notifications(PROFILE, MEMBERS, [], {}, [appt], datetime(2026, 11, 17, 13))
    assert [p["kind"] for p in day] == ["appointment_tomorrow"]


def test_notification_keys_are_stable():
    now = datetime(2026, 11, 15, 9, 5)
    first = [p["key"] for p in rules.plan_notifications(PROFILE, MEMBERS, [MED], {}, [], now)]
    second = [p["key"] for p in rules.plan_notifications(PROFILE, MEMBERS, [MED], {}, [], now)]
    assert first == second and len(first) == len(set(first))
