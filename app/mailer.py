"""Email sending. With no SMTP settings, emails are kept in the outbox only."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("orbit.mailer")


def _clean_header(value: str) -> str:
    """Strip line breaks so user text can never inject extra email headers."""
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())[:200]


class Mailer:
    def __init__(self, host: str = "", port: int = 465, user: str = "", password: str = "") -> None:
        self._host, self._port, self._user, self._password = host, port, user, password

    @property
    def enabled(self) -> bool:
        return bool(self._host and self._user and self._password)

    def send(self, to: list[str], subject: str, body: str) -> tuple[bool, str]:
        """Send one plain-text email. Returns (delivered, reason-if-not)."""
        if not self.enabled:
            return False, "Email sending is not configured; kept in the outbox."
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
