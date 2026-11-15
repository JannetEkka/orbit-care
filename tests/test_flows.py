"""Editing flows, email wording and the email senders."""

from datetime import timedelta

import httpx
import pytest

from app import notify
from app.config import Settings
from app.mailer import BrevoMailer, Mailer, make_mailer
from tests.conftest import HEADERS, TICK, post, put

MEDICINE = {"name": "Amlodipine", "dose": "5 mg", "slots": [{"time": "09:00"}], "stock": 30}
VISIT = {"doctor": "Dr. Mehta", "purpose": "BP check", "when": "2026-11-20T10:30:00", "repeat_days": 60}


def delete(client, path):
    return client.delete(path, headers=HEADERS)


# ---------- medicines ----------


def test_edit_medicine_changes_the_schedule(client, family):
    med = post(client, "/api/medicines", MEDICINE).json()
    changed = put(client, f"/api/medicines/{med['id']}", {**MEDICINE, "slots": [{"time": "21:00"}, {"time": "08:00"}]})
    assert changed.status_code == 200
    assert [s["time"] for s in changed.json()["slots"]] == ["08:00", "21:00"]
    assert [d["time"] for d in client.get("/api/today").json()["doses"]] == ["08:00", "21:00"]


def test_stopping_a_medicine_keeps_its_history(client, family):
    med = post(client, "/api/medicines", MEDICINE).json()
    assert delete(client, f"/api/medicines/{med['id']}").status_code == 200
    stopped = next(m for m in client.get("/api/medicines").json() if m["id"] == med["id"])
    assert stopped["active"] is False and stopped["end_date"]
    assert client.get("/api/today").json()["doses"] == []


def test_unknown_medicine_and_giver_are_refused(client, family):
    assert put(client, "/api/medicines/med_000000000000", MEDICINE).status_code == 404
    assert delete(client, "/api/medicines/med_000000000000").status_code == 404
    body = {**MEDICINE, "slots": [{"time": "09:00", "giver_id": "m_000000000000"}]}
    assert post(client, "/api/medicines", body).status_code == 422


@pytest.mark.parametrize("bad", [{"slots": []}, {"slots": [{"time": "25:00"}]}, {"name": ""}, {"stock": -1}])
def test_invalid_medicine_fields_are_refused(client, family, bad):
    assert post(client, "/api/medicines", {**MEDICINE, **bad}).status_code == 422


# ---------- appointments ----------


def test_visit_add_edit_remove(client, family):
    visit = post(client, "/api/appointments", VISIT).json()
    assert visit["when"] == "2026-11-20T10:30:00"
    edited = put(client, f"/api/appointments/{visit['id']}", {**VISIT, "purpose": "Blood test"}).json()
    assert edited["purpose"] == "Blood test"
    assert [a["purpose"] for a in client.get("/api/appointments").json()] == ["Blood test"]
    assert delete(client, f"/api/appointments/{visit['id']}").status_code == 200
    assert client.get("/api/appointments").json() == []
    assert delete(client, f"/api/appointments/{visit['id']}").status_code == 404
    assert put(client, f"/api/appointments/{visit['id']}", VISIT).status_code == 404


def test_upcoming_visit_shows_on_today(client, family):
    post(client, "/api/appointments", VISIT)
    upcoming = client.get("/api/today").json()["upcoming_appointments"]
    assert [a["doctor"] for a in upcoming] == ["Dr. Mehta"]


# ---------- people and profile ----------


def test_family_edits_and_removes_people(client, family):
    nurse = post(client, "/api/members", {"name": "Latha", "role": "caretaker", "passcode": "750319"}).json()
    edited = put(
        client, f"/api/members/{nurse['id']}", {"name": "Sister Latha", "role": "caretaker", "phone": "+91 98765 43210"}
    )
    assert edited.json()["name"] == "Sister Latha" and edited.json()["phone"] == "+91 98765 43210"
    assert delete(client, f"/api/members/{nurse['id']}").status_code == 200
    assert delete(client, f"/api/members/{nurse['id']}").status_code == 404


def test_you_cannot_lock_yourself_out(client, family):
    me = next(m for m in client.get("/api/today").json()["members"] if m["name"] == "Mary")
    assert put(client, f"/api/members/{me['id']}", {"name": "Mary", "role": "doctor"}).status_code == 409
    assert delete(client, f"/api/members/{me['id']}").status_code == 409


def test_new_passcode_works_and_the_old_one_stops(client, family):
    nurse = post(client, "/api/members", {"name": "Latha", "role": "caretaker", "passcode": "750319"}).json()
    put(client, f"/api/members/{nurse['id']}", {"name": "Latha", "role": "caretaker", "passcode": "613408"})
    client.cookies.clear()
    code = family["orbit_code"]
    assert post(client, "/api/login", {"orbit_code": code, "passcode": "750319"}).status_code == 401
    assert post(client, "/api/login", {"orbit_code": code, "passcode": "613408"}).json()["role"] == "caretaker"


def test_caretaker_cannot_manage_people_or_settings(client, family):
    post(client, "/api/members", {"name": "Latha", "role": "caretaker", "passcode": "750319"})
    client.cookies.clear()
    post(client, "/api/login", {"orbit_code": family["orbit_code"], "passcode": "750319"})
    assert post(client, "/api/members", {"name": "X", "role": "family", "passcode": "640218"}).status_code == 403
    assert put(client, "/api/profile", {"elder_name": "X"}).status_code == 403
    assert client.get("/api/audit").status_code == 403
    assert post(client, "/api/medicines", MEDICINE).status_code == 201  # but can manage medicines


def test_profile_saves_about_contacts_and_rules(client, family):
    body = {
        "elder_name": "Mrs. Rao",
        "about": {"address_as": "Amma", "likes": "Carnatic music"},
        "contacts": {"chemist_phone": "+91 80 1234 5678", "ambulance_phone": "108"},
        "settings": {"missed_after_min": 20, "escalate_after_min": 45},
    }
    assert put(client, "/api/profile", body).status_code == 200
    today = client.get("/api/today").json()
    assert today["elder_name"] == "Mrs. Rao" and today["about"]["address_as"] == "Amma"
    assert today["contacts"]["chemist_phone"] == "+91 80 1234 5678"
    assert today["settings"]["escalate_after_min"] == 45
    assert client.get("/api/bedside").json()["name"] == "Amma"


def test_profile_rejects_bad_phone_numbers(client, family):
    body = {"elder_name": "A", "contacts": {"chemist_phone": "call me <script>"}}
    assert put(client, "/api/profile", body).status_code == 422


# ---------- feelings, notes, outbox ----------


def test_feeling_is_recorded_once_per_day(client, family):
    post(client, "/api/feeling", {"value": "not_good"})
    post(client, "/api/feeling", {"value": "good"})
    assert client.get("/api/today").json()["feeling"] == "good"


def test_note_needs_text_or_a_tag(client, family):
    assert post(client, "/api/notes", {"text": "", "tags": []}).status_code == 422
    note = post(client, "/api/notes", {"tags": ["fall"]}).json()
    assert note["tags"] == ["fall"]
    assert client.get("/api/notes").json()[0]["id"] == note["id"]


def test_outbox_lists_what_was_sent(client, family, clock, mailer):
    post(client, "/api/medicines", MEDICINE)
    clock.advance(minutes=20)  # 08:50 local: the upcoming reminder is due
    client.post("/tasks/tick", headers=TICK)
    outbox = client.get("/api/outbox").json()
    assert outbox[0]["subject"].startswith("Mr. Thomas: Amlodipine 5 mg is due at 09:00")
    assert outbox[0]["delivered"] is True


def test_daily_email_cap_stops_sending(client, family, mailer, store):
    store.update_profile(family["orbit_code"], {"emails_day": "2026-11-15", "emails_sent": 40})
    post(client, "/api/help")
    assert mailer.sent == []
    assert "limit" in client.get("/api/outbox").json()[0]["detail"]


def test_old_demo_orbits_are_deleted(client, clock, store):
    pid = post(client, "/api/demo").json()["orbit_code"]
    clock.advance(hours=25)
    client.post("/tasks/tick", headers=TICK)
    assert store.get_profile(pid) is None


def test_one_broken_orbit_does_not_stop_the_others(client, family, store, monkeypatch):
    store.create_profile("BROKEN01", {"elder_name": "X", "settings": {"timezone": "Not/AZone"}})
    result = client.post("/tasks/tick", headers=TICK).json()
    assert result["failed"] == 1 and result["orbits"] == 2


# ---------- email wording ----------


@pytest.mark.parametrize(
    ("kind", "facts", "expected"),
    [
        (
            "upcoming",
            {"medicine": "Levodopa", "dose": "100 mg", "time": "13:00", "instructions": "Before food"},
            "Before food",
        ),
        ("missed", {"medicine": "Levodopa", "dose": "", "time": "13:00"}, "not marked as given"),
        ("escalated", {"medicine": "Levodopa", "dose": "", "time": "13:00"}, "already been reminded"),
        (
            "appointment_week",
            {"doctor": "Dr. Rao", "when": "Wed", "accompany": "", "purpose": "", "clinic_phone": "1"},
            "nobody is assigned",
        ),
        (
            "appointment_tomorrow",
            {"doctor": "Dr. Rao", "when": "Wed", "accompany": "Arun", "purpose": "Tremor"},
            "Going with Papa: Arun",
        ),
        (
            "checkup_due",
            {
                "doctor": "Dr. Mehta",
                "next_due": "2026-11-17",
                "last_visit": "2026-09-18",
                "overdue": True,
                "clinic_phone": "1",
            },
            "is overdue",
        ),
        ("refill", {"name": "Atorvastatin", "stock": 4, "days_left": 4}, "about 4 days"),
        ("help", {"time": "14:02", "by": "Bedside screen"}, "Please call or go to Papa now"),
        (
            "doctor_request",
            {"kind": "visit", "by": "Mary", "message": "", "medicines": "", "today": "t", "notes": "", "phone": "9"},
            "a home visit",
        ),
        ("digest", {"date": "Sunday 15 November", "text": "A calm day."}, "A calm day."),
    ],
)
def test_every_email_kind_has_clear_wording(kind, facts, expected):
    subject, body = notify.render(kind, facts, "Papa", "https://orbit.example")
    assert subject and expected in body + subject
    assert body.endswith("Open Orbit: https://orbit.example")


def test_unknown_email_kind_is_an_error():
    with pytest.raises(ValueError):
        notify.render("nonsense", {}, "Papa", "")


# ---------- email senders ----------


def test_smtp_mailer_without_settings_keeps_mail_in_the_outbox():
    assert Mailer().send(["a@example.com"], "s", "b") == (False, "Email sending is not configured; kept in the outbox.")


def test_smtp_mailer_reports_a_refused_message(monkeypatch):
    import smtplib

    class Refusing:
        def __init__(self, *args, **kwargs):
            raise smtplib.SMTPConnectError(421, "closed")

    monkeypatch.setattr(smtplib, "SMTP_SSL", Refusing)
    delivered, detail = Mailer("smtp.example.com", 465, "u@example.com", "p").send(["a@example.com"], "s", "b")
    assert not delivered and "did not accept" in detail


def test_smtp_mailer_sends(monkeypatch):
    import smtplib

    sent = []

    class Fake:
        def __init__(self, *args, **kwargs): ...
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def login(self, user, password):
            sent.append(("login", user))

        def send_message(self, message):
            sent.append(("send", message["To"], message["Subject"]))

    monkeypatch.setattr(smtplib, "SMTP_SSL", Fake)
    assert Mailer("smtp.example.com", 465, "u@example.com", "p").send(["a@example.com"], "Hi\r\nBcc: x", "b") == (
        True,
        "",
    )
    assert sent[1] == ("send", "a@example.com", "Hi Bcc: x")


def test_brevo_reports_a_rejected_key():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401)))
    delivered, detail = BrevoMailer("bad", "orbit@example.com", client=client).send(["a@example.com"], "s", "b")
    assert not delivered and "did not accept" in detail


def test_nobody_to_email_is_reported():
    assert BrevoMailer("k", "o@example.com").send([], "s", "b")[0] is False
    assert Mailer("h", 465, "u", "p").send([], "s", "b")[0] is False


def test_the_brevo_key_chooses_the_brevo_sender():
    assert isinstance(make_mailer(Settings(secret_key="x", brevo_api_key="k", mail_from="o@example.com")), BrevoMailer)
    assert isinstance(make_mailer(Settings(secret_key="x")), Mailer)


def test_settings_read_the_environment(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://orbit.example/")
    monkeypatch.setenv("ORBIT_COOKIE_SECURE", "0")
    monkeypatch.setenv("ORBIT_STORE", "Postgres")
    settings = Settings.from_env()
    assert settings.base_url == "https://orbit.example"
    assert settings.cookie_secure is False and settings.store_backend == "postgres"
    assert len(settings.secret_key) > 30


def test_demo_dates_move_with_the_clock(client, clock):
    clock.advance(days=3)
    post(client, "/api/demo")
    timeline = client.get("/api/summary?days=7&write=false").json()["timeline"]
    assert timeline[0]["date"] == (clock.now + timedelta(hours=5, minutes=30)).date().isoformat()


def test_on_render_the_app_runs_its_own_reminder_check(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("ORBIT_INPROCESS_TICK", raising=False)
    monkeypatch.delenv("ORBIT_KEEP_AWAKE", raising=False)
    settings = Settings.from_env()
    assert settings.inprocess_tick and settings.keep_awake
    monkeypatch.delenv("RENDER")
    assert not Settings.from_env().inprocess_tick
