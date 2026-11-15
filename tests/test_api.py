"""End-to-end flows through the HTTP API, with a fake clock and mailer."""

from tests.conftest import TICK, post, put


def add_member(client, name, role, passcode, email=""):
    response = post(client, "/api/members", {"name": name, "role": role, "passcode": passcode, "email": email})
    assert response.status_code == 201, response.text
    return response.json()


def sign_in(client, code, passcode):
    client.cookies.clear()
    response = post(client, "/api/login", {"orbit_code": code, "passcode": passcode})
    assert response.status_code == 200, response.text
    return response.json()


def add_levodopa(client, giver_id=None, stock=20):
    body = {
        "name": "Levodopa",
        "dose": "100 mg",
        "slots": [{"time": "09:00", "giver_id": giver_id}],
        "stock": stock,
        "colour": "yellow",
    }
    response = post(client, "/api/medicines", body)
    assert response.status_code == 201, response.text
    return response.json()


def test_family_adds_medicine_and_sees_it_today(client, family):
    add_levodopa(client)
    doses = client.get("/api/today").json()["doses"]
    assert [(d["time"], d["state"]) for d in doses] == [("09:00", "upcoming")]


def test_marking_given_counts_down_stock_once(client, family, clock):
    med = add_levodopa(client, stock=20)
    clock.advance(minutes=40)  # 09:10 local, the dose is due
    key = client.get("/api/today").json()["doses"][0]["key"]
    assert post(client, f"/api/doses/{key}/mark", {"status": "given"}).status_code == 200
    assert post(client, f"/api/doses/{key}/mark", {"status": "given"}).status_code == 200
    stock = next(m for m in client.get("/api/medicines").json() if m["id"] == med["id"])["stock"]
    assert stock == 19
    post(client, f"/api/doses/{key}/mark", {"status": "skipped"})
    stock = next(m for m in client.get("/api/medicines").json() if m["id"] == med["id"])["stock"]
    assert stock == 20


def test_unknown_dose_keys_are_refused(client, family):
    med = add_levodopa(client)
    assert post(client, f"/api/doses/{med['id']}_2026-11-15_0700/mark", {"status": "given"}).status_code == 404
    assert post(client, "/api/doses/nonsense/mark", {"status": "given"}).status_code == 404


def test_doctor_is_read_only(client, family):
    add_levodopa(client)
    add_member(client, "Dr Rao", "doctor", "750319")
    sign_in(client, family["orbit_code"], "750319")
    assert client.get("/api/today").status_code == 200
    assert client.get("/api/summary?days=7").status_code == 200
    assert post(client, "/api/medicines", {"name": "X", "slots": [{"time": "10:00"}]}).status_code == 403
    assert post(client, "/api/notes", {"text": "hi"}).status_code == 403
    assert client.get("/api/outbox").status_code == 403


def test_bedside_screen_can_only_confirm(client, family, clock):
    add_levodopa(client)
    add_member(client, "Bedside", "elder", "640218")
    result = sign_in(client, family["orbit_code"], "640218")
    assert result["role"] == "elder"
    assert client.get("/api/today").status_code == 403
    clock.advance(minutes=40)
    screen = client.get("/api/bedside").json()
    assert screen["due"] and "time for your medicine" in screen["speak"]
    key = screen["due"][0]["key"]
    assert post(client, f"/api/doses/{key}/mark", {"status": "skipped"}).status_code == 403
    assert post(client, f"/api/doses/{key}/mark", {"status": "given"}).status_code == 200
    assert client.get("/api/bedside").json()["due"] == []


def test_removed_member_loses_access_at_once(client, family):
    nurse = add_member(client, "Latha", "caretaker", "750319")
    sign_in(client, family["orbit_code"], "750319")
    nurse_cookie = dict(client.cookies)
    sign_in(client, family["orbit_code"], "482913")
    assert client.delete(f"/api/members/{nurse['id']}", headers={"x-orbit": "1"}).status_code == 200
    client.cookies.clear()
    client.cookies.update(nurse_cookie)
    assert client.get("/api/today").status_code == 401


def test_two_people_cannot_share_a_passcode(client, family):
    response = post(client, "/api/members", {"name": "Arun", "role": "family", "passcode": "482913"})
    assert response.status_code == 422


def test_missed_dose_escalates_by_email_exactly_once(client, family, clock, mailer):
    nurse = add_member(client, "Latha", "caretaker", "750319", "latha@example.com")
    add_member(client, "Arun", "family", "640218", "arun@example.com")
    add_levodopa(client, giver_id=nurse["id"])
    clock.advance(minutes=20)  # 08:50 local
    client.post("/tasks/tick", headers=TICK)
    clock.advance(minutes=45)  # 09:35: missed
    client.post("/tasks/tick", headers=TICK)
    clock.advance(minutes=30)  # 10:05: escalate
    client.post("/tasks/tick", headers=TICK)
    client.post("/tasks/tick", headers=TICK)  # a repeated tick sends nothing new
    subjects = [(to, subject) for to, subject, _ in mailer.sent]
    assert subjects[0] == (["latha@example.com"], "Mr. Thomas: Levodopa 100 mg is due at 09:00")
    assert "not marked as given" in subjects[1][1] and subjects[1][0] == ["latha@example.com"]
    assert subjects[2][1].startswith("Missed dose:")
    assert set(subjects[2][0]) == {"mary@example.com", "arun@example.com"}
    assert len(mailer.sent) == 3


def test_help_tells_the_circle_and_does_not_repeat(client, family, mailer):
    add_member(client, "Latha", "caretaker", "750319", "latha@example.com")
    first = post(client, "/api/help").json()
    second = post(client, "/api/help").json()
    assert set(first["told"]) == {"Mary", "Latha"} and not first["repeat"]
    assert second["repeat"]
    assert len(mailer.sent) == 1 and mailer.sent[0][1].startswith("HELP pressed")


def test_note_tags_are_suggested_from_text(client, family):
    note = post(client, "/api/notes", {"text": "He was shaking and very drowsy after lunch"}).json()
    assert set(note["tags"]) == {"tremor", "sleepy"}


def test_summary_falls_back_to_the_template_without_a_key(client, family):
    result = client.get("/api/summary?days=7").json()
    assert result["summary"]["source"] == "template"
    assert client.get("/api/summary?days=9").status_code == 422


def test_doctor_request_needs_a_doctor_email(client, family, mailer):
    assert post(client, "/api/doctor-request", {"kind": "call"}).status_code == 409
    add_member(client, "Dr Rao", "doctor", "750319", "rao@example.com")
    add_levodopa(client)
    result = post(client, "/api/doctor-request", {"kind": "visit", "message": "Tremor worse"}).json()
    assert result["to"] == ["Dr Rao"] and result["delivered"]
    body = mailer.sent[-1][2]
    assert "Levodopa" in body and "Tremor worse" in body


def test_profile_rules_must_escalate_after_the_reminder(client, family):
    body = {"elder_name": "Mr. Thomas", "settings": {"missed_after_min": 60, "escalate_after_min": 30}}
    assert put(client, "/api/profile", body).status_code == 422


def test_every_change_is_in_the_history(client, family):
    add_levodopa(client)
    actions = [row["action"] for row in client.get("/api/audit").json()]
    assert "medicine added" in actions and "orbit created" in actions


def test_demo_orbit_has_a_week_and_sends_no_real_email(client, mailer):
    response = post(client, "/api/demo")
    assert response.status_code == 201
    assert len(response.json()["passcodes"]) == 5
    summary = client.get("/api/summary?days=7").json()["facts"]
    assert summary["adherence"]["overall"]["scheduled"] > 30
    assert client.get("/api/bedside").json()["due"]
    assert client.get("/api/outbox").json()
    assert mailer.sent == []


def test_pages_are_served(client):
    for path in ("/", "/circle", "/bedside", "/healthz"):
        assert client.get(path).status_code == 200


def test_undo_restores_the_dose_and_the_stock(client, family, clock):
    med = add_levodopa(client, stock=20)
    clock.advance(minutes=40)
    key = client.get("/api/today").json()["doses"][0]["key"]
    post(client, f"/api/doses/{key}/mark", {"status": "given"})
    assert client.delete(f"/api/doses/{key}/mark", headers={"x-orbit": "1"}).status_code == 200
    dose = client.get("/api/today").json()["doses"][0]
    assert dose["state"] == "due"
    assert next(m for m in client.get("/api/medicines").json() if m["id"] == med["id"])["stock"] == 20


def test_summary_has_a_day_by_day_timeline(client):
    post(client, "/api/demo")
    timeline = client.get("/api/summary?days=7").json()["timeline"]
    assert len(timeline) == 7
    assert any("missed" in [d["state"] for d in row["doses"]] for row in timeline)
    assert any(row["tags"] for row in timeline)


def test_summary_without_writing_is_the_template(client):
    post(client, "/api/demo")
    result = client.get("/api/summary?days=7&write=false").json()
    assert result["summary"]["source"] == "template" and result["timeline"]
