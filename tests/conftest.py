"""Shared fixtures: an app with in-memory storage, a fake clock, a fake mailer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.store import MemoryStore
from app.summary import Summariser

HEADERS = {"x-orbit": "1"}
TICK = {"x-tick-token": "test-tick-token"}


class FakeClock:
    """UTC time that tests move forward by hand."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[list[str], str, str]] = []

    @property
    def enabled(self) -> bool:
        return True

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))
        return True, ""


@pytest.fixture
def clock() -> FakeClock:
    # 03:00 UTC = 08:30 in Asia/Kolkata
    return FakeClock(datetime(2026, 11, 15, 3, 0, tzinfo=UTC))


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def client(clock, mailer, store) -> TestClient:
    settings = Settings(
        secret_key="test-secret-key-test-secret-key-0123456789",
        tick_token="test-tick-token",
        cookie_secure=False,
    )
    app = create_app(settings=settings, store=store, mailer=mailer, summariser=Summariser(""), clock=clock)
    return TestClient(app)


def post(client: TestClient, path: str, body: dict | None = None, **kwargs):
    return client.post(path, json=body, headers=HEADERS, **kwargs)


def put(client: TestClient, path: str, body: dict):
    return client.put(path, json=body, headers=HEADERS)


@pytest.fixture
def family(client) -> dict:
    """A new orbit, signed in as its first family member."""
    response = post(
        client,
        "/api/orbits",
        {"elder_name": "Mr. Thomas", "your_name": "Mary", "your_email": "mary@example.com", "passcode": "482913"},
    )
    assert response.status_code == 201
    return response.json()
