"""Passcodes, signed session tokens and sign-in lockout.

Passcodes are never stored: only a salted scrypt hash is. Sessions are a signed,
expiring token kept in an HttpOnly cookie.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
ORBIT_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
_SEQUENCES = ("0123456789012345", "9876543210987654")


def new_orbit_code(length: int = 8) -> str:
    """A random code that identifies one elder's orbit. Not a secret by itself."""
    return "".join(secrets.choice(ORBIT_CODE_ALPHABET) for _ in range(length))


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def new_passcode(length: int = 6) -> str:
    """A random numeric passcode that passes `validate_passcode`."""
    while True:
        code = "".join(secrets.choice("0123456789") for _ in range(length))
        try:
            validate_passcode(code)
        except ValueError:
            continue
        return code


def validate_passcode(passcode: str) -> None:
    """Reject passcodes that are too short or trivially guessable."""
    if not passcode.isdigit() or not 6 <= len(passcode) <= 12:
        raise ValueError("A passcode is 6 to 12 digits.")
    if len(set(passcode)) == 1:
        raise ValueError("A passcode cannot be one digit repeated.")
    if any(passcode in seq for seq in _SEQUENCES):
        raise ValueError("A passcode cannot be a simple run like 123456.")


def hash_passcode(passcode: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(passcode.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def passcode_key(passcode: str, pid: str, secret: str) -> str:
    """A keyed fingerprint used only to find which member a passcode belongs to.

    It lets sign-in run one slow scrypt check instead of one per member. Without the
    server secret it cannot be brute-forced from a copy of the database.
    """
    return hmac.new(secret.encode(), f"{pid}:{passcode}".encode(), hashlib.sha256).hexdigest()[:32]


def candidates_for(members: list[dict], key: str) -> list[dict]:
    """Members whose fingerprint matches, plus any older member saved without one."""
    return [m for m in members if m.get("passcode_key") in (key, None)]


def verify_passcode(passcode: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = _unb64(salt_b64)
        expected = _unb64(digest_b64)
        digest = hashlib.scrypt(passcode.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def make_token(payload: dict, secret: str, now: datetime, ttl: timedelta) -> str:
    body = dict(payload, exp=int((now + ttl).timestamp()))
    raw = _b64(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
    return f"{raw}.{_sign(raw, secret)}"


def read_token(token: str, secret: str, now: datetime) -> dict | None:
    """Return the payload of a valid, unexpired token, else None."""
    try:
        raw, signature = token.split(".")
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(signature, _sign(raw, secret)):
        return None
    try:
        payload = json.loads(_unb64(raw))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < now.timestamp():
        return None
    return payload


def is_locked(profile: dict, now: datetime) -> bool:
    until = profile.get("locked_until")
    return bool(until) and datetime.fromisoformat(until) > now


def after_failed_attempt(profile: dict, now: datetime) -> dict:
    """Fields to save after a wrong passcode: count it, and lock after too many."""
    failed = int(profile.get("failed_attempts", 0)) + 1
    if failed >= MAX_FAILED_ATTEMPTS:
        locked_until = (now + timedelta(minutes=LOCK_MINUTES)).isoformat()
        return {"failed_attempts": 0, "locked_until": locked_until}
    return {"failed_attempts": failed}


def _sign(raw: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest())


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
