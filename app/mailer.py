"""Email sending.

Two ways to send, chosen by settings:
- Brevo's HTTPS API (BREVO_API_KEY), for hosts that block outgoing SMTP ports;
- SMTP (SMTP_USER and SMTP_PASSWORD), e.g. a Gmail app password.
With neither, emails are kept in the in-app outbox only.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .config import Settings

log = logging.getLogger("orbit.mailer")
BREVO_URL = "https://api.brevo.com/v3/smtp/email"
NOT_CONFIGURED = "Email sending is not configured; kept in the outbox."


def _clean_header(value: str) -> str:
    """Strip line breaks so user text can never inject extra email headers."""
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())[:200]


class Mailer:
    """SMTP over TLS."""

    def __init__(self, host: str = "", port: int = 465, user: str = "", password: str = "") -> None:
        self._host, self._port, self._user, self._password = host, port, user, password

    @property
    def enabled(self) -> bool:
        return bool(self._host and self._user and self._password)

    def send(self, to: list[str], subject: str, body: str) -> tuple[bool, str]:
        """Send one plain-text email. Returns (delivered, reason-if-not)."""
        if not self.enabled:
            return False, NOT_CONFIGURED
        if not to:
            return False, "Nobody in the circle has an email address."
        message = EmailMessage()
        message["From"] = f"Orbit <{self._user}>"
        message["To"] = ", ".join(_clean_header(address) for address in to)
        message["Subject"] = _clean_header(subject)
        message.set_content(body)
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(self._host, self._port, context=context, timeout=15) as smtp:
                smtp.login(self._user, self._password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as error:
            log.warning("Email not delivered: %s", type(error).__name__)
            return False, "The mail server did not accept the message."
        return True, ""


class BrevoMailer:
    """Brevo transactional email over HTTPS (works where SMTP ports are blocked)."""

    def __init__(self, api_key: str, sender: str, client: httpx.Client | None = None) -> None:
        self._api_key, self._sender = api_key, sender
        self._client = client or httpx.Client(timeout=15)

    @property
    def enabled(self) -> bool:
        return bool(self._api_key and self._sender)

    def send(self, to: list[str], subject: str, body: str) -> tuple[bool, str]:
        if not self.enabled:
            return False, NOT_CONFIGURED
        if not to:
            return False, "Nobody in the circle has an email address."
        payload = {
            "sender": {"name": "Orbit", "email": self._sender},
            "to": [{"email": address} for address in to],
            "subject": _clean_header(subject),
            "textContent": body,
        }
        try:
            response = self._client.post(BREVO_URL, headers={"api-key": self._api_key}, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as error:
            log.warning("Email not delivered: %s", type(error).__name__)
            return False, "The email service did not accept the message."
        return True, ""


def make_mailer(settings: Settings) -> Mailer | BrevoMailer:
    if settings.brevo_api_key:
        return BrevoMailer(settings.brevo_api_key, settings.mail_from)
    return Mailer(settings.smtp_host, settings.smtp_port, settings.smtp_user, settings.smtp_password)
