"""Customer accounts: e-mail and password, with nothing outside the service.

An account gathers what a customer already had scattered in links: the
reports they uploaded or saved, the access codes they redeemed or added,
and what they paid for. It never changes what a report says or how a
report is unlocked; a report link keeps working without an account, and the
free preview needs none.

Design choices, all standard library:

* Passwords are hashed with scrypt (``hashlib.scrypt``, N=2**14, r=8, p=1)
  and a random 16-byte salt; only the hash is stored.
* A session is a random 32-byte token in an ``HttpOnly`` ``SameSite=Lax``
  cookie (``Secure`` when the service runs on https); the database keeps
  only its SHA-256, so a copy of the database cannot sign anyone in.
* Every account form carries a CSRF token: a double-submit cookie before
  sign-in, the session's own token after.
* E-mail is not verified and no e-mail is ever sent: the service has no
  mail provider. The hooks for one (confirmation and reset by e-mail) are
  :data:`EMAIL_HOOKS`; until then the owner issues a one-time reset link
  from the panel.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from urllib.parse import urlsplit

#: scrypt cost: about 16 MB and a few tens of milliseconds per hash.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
_SCHEME = "scrypt"

MIN_PASSWORD_CHARS = 10
MAX_PASSWORD_CHARS = 256
MAX_EMAIL_CHARS = 254
SESSION_DAYS = 30
RESET_HOURS = 24
#: Per address and per e-mail, per hour.
MAX_FAILED_SIGNINS_PER_HOUR = 10
MAX_SIGNUPS_PER_HOUR = 5
MAX_ACCOUNT_ACTIONS_PER_HOUR = 30

SESSION_COOKIE = "rigor_session"
CSRF_COOKIE = "rigor_csrf"

#: What an outside e-mail service would switch on, and what the owner adds.
EMAIL_HOOKS = ("confirm_email", "reset_by_email")

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalise_email(value: str) -> str:
    return value.strip().lower()


def valid_email(value: str) -> bool:
    clean = normalise_email(value)
    if not 3 <= len(clean) <= MAX_EMAIL_CHARS:
        return False
    if any(not char.isprintable() for char in clean):
        return False
    return bool(_EMAIL.match(clean))


def password_problem(password: str) -> str:
    """``""`` when the password is acceptable, else a copy key for the form."""
    if len(password) < MIN_PASSWORD_CHARS:
        return "password_short"
    if len(password) > MAX_PASSWORD_CHARS:
        return "password_long"
    if "\x00" in password:
        return "password_short"
    return ""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """``scrypt$N$r$p$salt$hash``: everything needed to check it later."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"{_SCHEME}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(stored: str, password: str) -> bool:
    """Constant-time check against a stored hash; a malformed hash is ``False``."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != _SCHEME:
            return False
        expected = _unb64(digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


#: Checked when an e-mail is unknown, so a wrong address costs the same time.
_DUMMY_HASH = hash_password("not-a-real-password", salt=b"\x00" * 16)


def burn_time(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


def new_secret() -> str:
    """A token for a cookie or a link (256 bits)."""
    return secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def same_secret(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


#: Where a form may send the customer back after signing in.
_NEXT_PREFIXES = ("/audits/", "/cuenta", "/account")


def safe_next(value: str | None) -> str:
    """A same-site path from a ``next`` field, or ``""``.

    Only paths on this service are accepted, never a full address, so a
    crafted sign-in link cannot send someone to another site.
    """
    if not value or len(value) > 600:
        return ""
    if any(not char.isprintable() or char in "\\" for char in value):
        return ""
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or value.startswith("//"):
        return ""
    if not parts.path.startswith(_NEXT_PREFIXES):
        return ""
    return value


__all__ = [
    "CSRF_COOKIE",
    "EMAIL_HOOKS",
    "MAX_FAILED_SIGNINS_PER_HOUR",
    "MAX_SIGNUPS_PER_HOUR",
    "MIN_PASSWORD_CHARS",
    "RESET_HOURS",
    "SESSION_COOKIE",
    "SESSION_DAYS",
    "burn_time",
    "hash_password",
    "hash_secret",
    "new_secret",
    "normalise_email",
    "password_problem",
    "safe_next",
    "same_secret",
    "valid_email",
    "verify_password",
]
