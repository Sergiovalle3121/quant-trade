"""Customer accounts: e-mail and password, with nothing outside the service.

An account gathers what a customer already had scattered in links: the
reports they uploaded or saved, the access codes they redeemed or added,
and what they paid for. It never changes what a report says or how a
report is unlocked; a report link keeps working without an account. The free
preview needs one: :data:`FREE_PREVIEWS_PER_MONTH` a month per account, after a
first full report that is free once (:data:`WELCOME_FULL_REPORT`).

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
import ipaddress
import re
import secrets
from datetime import UTC, datetime
from typing import Any
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
#: Failed sign-ins per hour for one (address, e-mail) pair; the per-address
#: and per-e-mail ceilings are higher so one stranger cannot lock the owner
#: out. The per-e-mail ceiling also slows guessing spread over many addresses:
#: past it, an address that already failed on that e-mail waits for the hour.
MAX_FAILED_SIGNINS_PER_HOUR = 10
MAX_FAILED_SIGNINS_PER_IP = 50
MAX_FAILED_SIGNINS_PER_EMAIL = 50
#: Tries an address gets on an e-mail past that e-mail's ceiling, so a
#: stranger who knows the e-mail cannot lock the owner out.
SIGNIN_TRIES_PAST_EMAIL_CEILING = 2
MAX_SIGNUPS_PER_HOUR = 5
MAX_ACCOUNT_ACTIONS_PER_HOUR = 30

#: The free tier: an account gets this many free previews per calendar month
#: (UTC). Past it, an upload needs a credit or a code; full reports stay paid.
FREE_PREVIEWS_PER_MONTH = 3
#: Free previews per network address per calendar month, across accounts:
#: slows throwaway accounts without blocking a shared office or carrier.
FREE_PREVIEWS_PER_IP_PER_MONTH = 10

#: A new account's first upload comes out as a free full report, once. The
#: same browser (``DEVICE_COOKIE``) or the same file never gets a second one
#: on another account, and each network address gets a few a month.
WELCOME_FULL_REPORT = True
WELCOME_REPORTS_PER_IP_PER_MONTH = 3
#: "Invita a un colega": an account whose invite link brings a new account
#: gets this many full-report credits once the new account's free first
#: report exists (so the free tier's browser, file and address limits
#: already held), at most ``REFERRAL_MONTHLY_CAP`` times a calendar month.
REFERRAL_CREDITS = 1
REFERRAL_MONTHLY_CAP = 5
#: The sign-up query parameter that carries an invite token.
INVITE_PARAM = "invita"
DEVICE_COOKIE = "rigor_device"
DEVICE_DAYS = 400

SESSION_COOKIE = "rigor_session"
CSRF_COOKIE = "rigor_csrf"

#: What an outside e-mail service would switch on, and what the owner adds.
EMAIL_HOOKS = ("confirm_email", "reset_by_email")

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def month_start(at: datetime) -> datetime:
    """The first instant of ``at``'s calendar month, in UTC."""
    at = at.astimezone(UTC)
    return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def normalise_email(value: str) -> str:
    return value.strip().lower()


def valid_email(value: str) -> bool:
    clean = normalise_email(value)
    if not 3 <= len(clean) <= MAX_EMAIL_CHARS:
        return False
    if any(not char.isprintable() for char in clean):
        return False
    return bool(_EMAIL.match(clean))


def password_problem(password: str, *, email: str = "") -> str:
    """``""`` when the password is acceptable, else a copy key for the form."""
    if len(password) < MIN_PASSWORD_CHARS:
        return "password_short"
    if len(password) > MAX_PASSWORD_CHARS:
        return "password_long"
    if any(not char.isprintable() and char != " " for char in password):
        return "password_bad"
    if common_password(password, email=email):
        return "password_common"
    return ""


#: Words that head the most common long passwords (English, Spanish and
#: Portuguese), checked offline. A password that is one of them, possibly
#: repeated, with digits, a year or symbols around it, is refused: those
#: fall first to a guessing list at a couple of thousand tries an hour.
COMMON_WORDS = frozenset(
    (
        "password",
        "passw0rd",
        "passwort",
        "contraseña",
        "contrasena",
        "senha",
        "minhasenha",
        "qwerty",
        "qwertyuiop",
        "asdfgh",
        "asdfghjkl",
        "zxcvbnm",
        "azerty",
        "iloveyou",
        "teamo",
        "teamomucho",
        "tequiero",
        "amor",
        "amorcito",
        "princesa",
        "princess",
        "sunshine",
        "football",
        "futbol",
        "baseball",
        "soccer",
        "basketball",
        "dragon",
        "monkey",
        "letmein",
        "welcome",
        "bienvenido",
        "admin",
        "administrator",
        "administrador",
        "master",
        "login",
        "abc",
        "abcdef",
        "abcdefg",
        "abcdefgh",
        "trustno1",
        "superman",
        "batman",
        "shadow",
        "michael",
        "jennifer",
        "jordan",
        "hunter",
        "killer",
        "freedom",
        "whatever",
        "starwars",
        "pokemon",
        "charlie",
        "donald",
        "computer",
        "internet",
        "samsung",
        "iphone",
        "google",
        "facebook",
        "secret",
        "secreto",
        "mexico",
        "america",
        "brasil",
        "argentina",
        "colombia",
        "chile",
        "españa",
        "espana",
        "madrid",
        "barcelona",
        "realmadrid",
        "boca",
        "river",
        "corinthians",
        "flamengo",
        "trading",
        "trader",
        "forex",
        "bitcoin",
        "crypto",
        "money",
        "dinero",
        "dineros",
        "millonario",
        "rigor",
        "rigoraudit",
        "metatrader",
        "mt4",
        "mt5",
        "tradingview",
        "binance",
        "bybit",
        "changeme",
        "cambiame",
        "mudar",
        "default",
        "test",
        "testing",
        "prueba",
        "pruebas",
        "usuario",
        "user",
        "guest",
        "invitado",
        "family",
        "familia",
        "jesus",
        "jesucristo",
        "dios",
        "diosesamor",
        "maria",
        "jose",
    )
)

_KEYBOARD_ROWS = (
    "`1234567890-=",
    "qwertyuiop[]\\",
    "asdfghjkl;'",
    "zxcvbnm,./",
    "1qaz2wsx3edc4rfv5tgb6yhn7ujm8ik,9ol.0p;/",
    "qazwsxedcrfvtgbyhnujmikolp",
    "1q2w3e4r5t6y7u8i9o0p",
    "zaq12wsxcde34rfvbgt56yhnmju78ik,.lo90p;/-",
    "abcdefghijklmnopqrstuvwxyz",
)


_LEET = str.maketrans({"@": "a", "0": "o", "1": "i", "3": "e", "4": "a", "$": "s", "5": "s"})


def _is_run(text: str) -> bool:
    """A stretch of a keyboard row, the alphabet or digits, either direction."""
    for row in _KEYBOARD_ROWS:
        if text in row or text in row[::-1]:
            return True
        doubled = row + row  # 0123456789 wraps to 0123...
        if text in doubled or text in doubled[::-1]:
            return True
    return False


def _repeats(text: str) -> bool:
    """Built from one short unit repeated (``aaaa``, ``abcabc``, ``12121212``)."""
    for size in range(1, len(text) // 2 + 1):
        unit = text[:size]
        if len(text) % size == 0 and unit * (len(text) // size) == text:
            return True
    return False


def common_password(password: str, *, email: str = "") -> bool:
    """Whether ``password`` is one of the easy guesses a list tries first."""
    text = password.strip().lower()
    compact = re.sub(r"[\s._\-!@#$%^&*+=?¡¿]+", "", text)
    if not compact or _repeats(compact) or _is_run(compact) or len(set(compact)) <= 3:
        return True
    # A common word (or the e-mail's name) with only digits, a year or
    # symbols around it, or the word repeated.
    core = re.sub(r"^[0-9]+|[0-9]+$", "", compact)
    words = set(COMMON_WORDS)
    local = email.split("@", 1)[0].lower() if email else ""
    if len(local) >= 3:
        words.add(re.sub(r"[^a-z0-9ñ]+", "", local))
    if not core:
        return True  # digits only: dates, phone-like runs and counts fall fast
    if core in words or (_repeats(core) and any(core.startswith(w) for w in words if w)):
        return True
    if any(core == word * (len(core) // len(word)) for word in words if word) or _is_run(core):
        return True
    # Leetspeak: "P@ssw0rd2024" is "password" with a year.
    kept = re.sub(r"[\s._\-!#%^&*+=?¡¿]+", "", text)
    leet = re.sub(r"^[0-9]+|[0-9]+$", "", kept).translate(_LEET)
    return leet != core and leet in words


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


#: A recovery key: 20 characters from 32 unambiguous ones (100 random bits),
#: shown once in groups of five. Tries are limited per network and per e-mail.
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
RECOVERY_KEY_CHARS = 20
MAX_RECOVERY_TRIES_PER_HOUR = 10


def new_recovery_key() -> str:
    raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_KEY_CHARS))
    return "-".join(raw[i : i + 5] for i in range(0, RECOVERY_KEY_CHARS, 5))


def recovery_key_hash(text: str) -> str:
    """The stored form of a recovery key, however it was typed (case, dashes, spaces)."""
    return hash_secret("recovery:" + re.sub(r"[^A-Z0-9]", "", text.upper()))


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def same_secret(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


#: Where a form may send the customer back after signing in.
_NEXT_PREFIXES = ("/audits/", "/cuenta", "/account", "/pt/conta")
_NEXT_HOMES = ("/", "/en", "/pt")


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
    # The home page only as itself (with the upload form's anchor), never
    # as a prefix: "/" would otherwise allow every path.
    home = parts.path in _NEXT_HOMES and not parts.query
    if not (home or parts.path.startswith(_NEXT_PREFIXES)):
        return ""
    return value


__all__ = [
    "CSRF_COOKIE",
    "DEVICE_COOKIE",
    "EMAIL_HOOKS",
    "FREE_PREVIEWS_PER_IP_PER_MONTH",
    "FREE_PREVIEWS_PER_MONTH",
    "MAX_FAILED_SIGNINS_PER_EMAIL",
    "MAX_FAILED_SIGNINS_PER_HOUR",
    "MAX_FAILED_SIGNINS_PER_IP",
    "MAX_ACCOUNT_ACTIONS_PER_HOUR",
    "MAX_SIGNUPS_PER_HOUR",
    "MIN_PASSWORD_CHARS",
    "INVITE_PARAM",
    "REFERRAL_CREDITS",
    "REFERRAL_MONTHLY_CAP",
    "RESET_HOURS",
    "SESSION_COOKIE",
    "SIGNIN_TRIES_PAST_EMAIL_CEILING",
    "SESSION_DAYS",
    "WELCOME_FULL_REPORT",
    "WELCOME_REPORTS_PER_IP_PER_MONTH",
    "burn_time",
    "common_password",
    "claim_month",
    "content_fingerprint",
    "hash_password",
    "hash_secret",
    "month_start",
    "network_address",
    "network_key",
    "new_secret",
    "normalise_email",
    "password_problem",
    "safe_next",
    "same_secret",
    "valid_email",
    "verify_password",
]


def content_fingerprint(frame: Any) -> str:
    """SHA-256 of what a file says, not of its bytes.

    The curve's timestamps and returns rounded to five decimals: the same
    track record with a trailing newline, other line endings, extra spaces
    or renamed columns gives the same fingerprint, so it cannot collect a
    second free full report on another account.
    """
    digest = hashlib.sha256()
    for stamp, ret in zip(frame["timestamp"], frame["ret"], strict=False):
        value = 0.0 if ret != ret else round(float(ret), 5)  # NaN on the first row
        digest.update(f"{stamp}|{value:.5f}\n".encode())
    return digest.hexdigest()


def claim_month(at: datetime) -> str:
    return at.strftime("%Y-%m")


def network_address(client_ip: str) -> str:
    """The network an address stands for in the free tier's limits.

    An IPv6 customer gets a whole /64 and can rotate addresses inside it at
    will, so an IPv6 address counts as its /64 (``2001:db8:1:2::/64``); an
    IPv4 address counts as itself. Anything unparsable is kept as given.
    """
    try:
        address = ipaddress.ip_address(client_ip.strip())
    except ValueError:
        return client_ip
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def network_key(client_ip: str) -> str:
    """The address's network as it goes into a claim key: hashed, never in clear."""
    return hashlib.sha256(network_address(client_ip).encode("utf-8")).hexdigest()[:32]
