"""Runtime settings, read once from environment variables."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Everything the app needs from its environment. No secret has a default."""

    secret_key: str
    store_backend: str = "memory"
    tick_token: str = ""
    base_url: str = ""
    cookie_secure: bool = True
    inprocess_tick: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    daily_email_cap: int = 40
    max_demo_orbits: int = 300

    @classmethod
    def from_env(cls) -> Settings:
        # Without ORBIT_SECRET_KEY a random key is used: sessions then end when the
        # process restarts, which is safe, and production sets the variable.
        return cls(
            secret_key=os.environ.get("ORBIT_SECRET_KEY") or secrets.token_urlsafe(48),
            store_backend=os.environ.get("ORBIT_STORE", "memory").strip().lower(),
            tick_token=os.environ.get("ORBIT_TICK_TOKEN", ""),
            base_url=os.environ.get("ORBIT_BASE_URL", "").rstrip("/"),
            cookie_secure=_flag("ORBIT_COOKIE_SECURE", True),
            inprocess_tick=_flag("ORBIT_INPROCESS_TICK", False),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"),
            smtp_host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(os.environ.get("SMTP_PORT", "465")),
            smtp_user=os.environ.get("SMTP_USER", ""),
            smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        )
