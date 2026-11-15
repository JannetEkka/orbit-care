"""Passcodes, sessions and the protections around them."""

from datetime import datetime, timedelta

import pytest

from app import security
from tests.conftest import HEADERS, post

NOW = datetime(2026, 11, 15, 9, 0)


def test_passcode_is_hashed_and_verified():
    stored = security.hash_passcode("482913")
    assert "482913" not in stored
    assert security.verify_passcode("482913", stored)
    assert not security.verify_passcode("482914", stored)
    assert not security.verify_passcode("482913", "garbage")


@pytest.mark.parametrize("weak", ["123456", "111111", "987654", "12345", "abcdef"])
def test_weak_passcodes_are_refused(weak):
    with pytest.raises(ValueError):
        security.validate_passcode(weak)


def test_generated_passcodes_are_valid():
    for _ in range(50):
        security.validate_passcode(security.new_passcode())


def test_token_rejects_tampering_and_expiry():
    token = security.make_token({"pid": "P", "mid": "M"}, "secret", NOW, timedelta(hours=1))
    assert security.read_token(token, "secret", NOW)["mid"] == "M"
    assert security.read_token(token, "other-secret", NOW) is None
    assert security.read_token(token, "secret", NOW + timedelta(hours=2)) is None
    raw, signature = token.split(".")
    assert security.read_token(raw + "x." + signature, "secret", NOW) is None
    assert security.read_token("not-a-token", "secret", NOW) is None


def test_lockout_after_five_wrong_passcodes(client, family):
    client.cookies.clear()
    code = family["orbit_code"]
    for _ in range(5):
        assert post(client, "/api/login", {"orbit_code": code, "passcode": "000001"}).status_code == 401
    locked = post(client, "/api/login", {"orbit_code": code, "passcode": "482913"})
    assert locked.status_code == 423


def test_wrong_code_and_wrong_passcode_look_the_same(client, family):
    client.cookies.clear()
    unknown = post(client, "/api/login", {"orbit_code": "ZZZZZZZZ", "passcode": "482913"})
    wrong = post(client, "/api/login", {"orbit_code": family["orbit_code"], "passcode": "750319"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_api_needs_a_session(client):
    assert client.get("/api/today").status_code == 401


def test_state_changes_need_the_custom_header(client, family):
    response = client.post("/api/notes", json={"text": "x"})
    assert response.status_code == 400


def test_session_cookie_is_httponly_and_strict(client):
    response = post(client, "/api/orbits", {"elder_name": "A", "your_name": "B", "passcode": "482913"})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_security_headers_are_set(client):
    response = client.get("/")
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_tick_needs_the_secret(client):
    assert client.post("/tasks/tick").status_code == 403
    assert client.post("/tasks/tick", headers={"x-tick-token": "wrong"}).status_code == 403


def test_unknown_fields_are_rejected(client, family):
    response = post(client, "/api/notes", {"text": "ok", "role": "family"})
    assert response.status_code == 422


def test_header_injection_is_stripped():
    from app.mailer import _clean_header

    assert "\n" not in _clean_header("Hello\r\nBcc: attacker@example.com")
    assert HEADERS["x-orbit"] == "1"


def test_sign_in_runs_one_slow_hash_check(client, family, monkeypatch):
    for i, code in enumerate(("750319", "640218", "593027")):
        post(client, "/api/members", {"name": f"P{i}", "role": "family", "passcode": code})
    checks = []
    original = security.verify_passcode
    monkeypatch.setattr(security, "verify_passcode", lambda p, s: checks.append(1) or original(p, s))
    client.cookies.clear()
    assert post(client, "/api/login", {"orbit_code": family["orbit_code"], "passcode": "640218"}).status_code == 200
    assert len(checks) == 1


def test_static_files_are_compressed_and_cached(client):
    response = client.get("/static/css/orbit.css", headers={"accept-encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert "max-age" in response.headers["cache-control"]


def test_isolation_headers_are_set(client):
    headers = client.get("/").headers
    assert headers["cross-origin-opener-policy"] == "same-origin"
    assert headers["cross-origin-resource-policy"] == "same-origin"
    assert "max-age" in headers["strict-transport-security"]


def test_production_cookie_uses_the_host_prefix(store, clock, mailer):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from app.summary import Summariser

    settings = Settings(secret_key="k" * 40, cookie_secure=True)
    app = create_app(settings=settings, store=store, mailer=mailer, summariser=Summariser(""), clock=clock)
    response = TestClient(app, base_url="https://testserver").post(
        "/api/orbits", json={"elder_name": "A", "your_name": "B", "passcode": "482913"}, headers=HEADERS
    )
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-orbit_session=") and "Secure" in cookie and "Domain" not in cookie
