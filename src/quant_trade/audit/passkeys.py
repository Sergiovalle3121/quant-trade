"""Passkeys (WebAuthn): sign in with the phone's or computer's lock instead of a password.

A thin layer over ``webauthn`` (py_webauthn, Duo Labs). The browser does the
cryptography; this module makes the options the page hands to
``navigator.credentials`` and checks what comes back.

- The relying party is the host of ``AUDIT_BASE_URL``. A passkey is bound to
  that host by the browser, so a new domain means new passkeys: the password,
  the two-step code and the recovery key keep working and are the way back in.
- Signing in with a passkey alone asks the device to verify its owner
  (fingerprint, face or PIN): the device plus that check are two factors, so
  it also stands in for the two-step code.
- Only the public key, the credential id and a counter are stored; the private
  key never leaves the customer's device.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidJSONStructure,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

#: How long the passkey page stays valid, and its cookie.
CHALLENGE_MINUTES = 5
COOKIE = "rigor_passkey"
#: Passkeys per account (a phone, a laptop, a spare security key...).
MAX_PER_ACCOUNT = 10
#: Passkey pages opened per network per hour (each one stores a challenge).
MAX_STARTS_PER_HOUR = 30
#: Largest credential the browser may post back (a registration carries the key).
MAX_CREDENTIAL_CHARS = 20_000
LABEL_CHARS = 60
TIMEOUT_MS = 120_000


@dataclass(frozen=True)
class RelyingParty:
    """The site a passkey belongs to: ``rp_id`` is the host, ``origin`` the address."""

    rp_id: str
    origin: str
    name: str


@dataclass(frozen=True)
class NewPasskey:
    credential_id: str
    public_key: str
    sign_count: int
    transports: str


@dataclass(frozen=True)
class UsedPasskey:
    credential_id: str
    new_sign_count: int


def relying_party(base_url: str, name: str) -> RelyingParty | None:
    """The relying party for ``base_url``, or ``None`` when it has no usable host."""
    parts = urlsplit(base_url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return None
    return RelyingParty(rp_id=host, origin=f"{parts.scheme}://{parts.netloc.lower()}", name=name)


def new_challenge() -> bytes:
    return secrets.token_bytes(32)


def encode(raw: bytes) -> str:
    return bytes_to_base64url(raw)


def decode(text: str) -> bytes:
    return base64url_to_bytes(text)


def registration_options(
    rp: RelyingParty,
    *,
    challenge: bytes,
    user_handle: bytes,
    user_name: str,
    existing: list[str],
) -> str:
    """JSON options for ``navigator.credentials.create``.

    A discoverable credential (so the sign-in page needs no e-mail), and the
    device must check its owner. ``existing`` keeps the same device from being
    added twice.
    """
    options = generate_registration_options(
        rp_id=rp.rp_id,
        rp_name=rp.name,
        user_name=user_name,
        user_id=user_handle,
        user_display_name=user_name,
        challenge=challenge,
        timeout=TIMEOUT_MS,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(item)) for item in existing
        ],
    )
    return str(options_to_json(options))


def authentication_options(rp: RelyingParty, *, challenge: bytes, allowed: list[str]) -> str:
    """JSON options for ``navigator.credentials.get``; empty ``allowed`` lets the device choose."""
    options = generate_authentication_options(
        rp_id=rp.rp_id,
        challenge=challenge,
        timeout=TIMEOUT_MS,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(item)) for item in allowed
        ],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return str(options_to_json(options))


def _parsed(credential: str) -> dict[str, Any] | None:
    if not credential or len(credential) > MAX_CREDENTIAL_CHARS:
        return None
    try:
        data = json.loads(credential)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def credential_id(credential: str) -> str:
    """The id a posted credential names ("" when it is not one)."""
    data = _parsed(credential)
    value = data.get("id") if data else None
    if not isinstance(value, str) or not 1 <= len(value) <= 1400:
        return ""
    try:
        return encode(base64url_to_bytes(value))
    except ValueError:
        return ""


def verify_new(rp: RelyingParty, credential: str, *, challenge: bytes) -> NewPasskey | None:
    """The passkey a registration made, or ``None`` if anything does not check out."""
    data = _parsed(credential)
    if data is None:
        return None
    try:
        verified = verify_registration_response(
            credential=data,
            expected_challenge=challenge,
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
            require_user_verification=True,
        )
    except (InvalidRegistrationResponse, InvalidJSONStructure, ValueError, KeyError, TypeError):
        return None
    response = data.get("response")
    transports = response.get("transports") if isinstance(response, dict) else None
    names = (
        [t for t in transports if isinstance(t, str)][:6] if isinstance(transports, list) else []
    )
    return NewPasskey(
        credential_id=encode(verified.credential_id),
        public_key=encode(verified.credential_public_key),
        sign_count=int(verified.sign_count),
        transports=",".join(t[:20] for t in names),
    )


def verify_use(
    rp: RelyingParty,
    credential: str,
    *,
    challenge: bytes,
    public_key: str,
    sign_count: int,
) -> UsedPasskey | None:
    """Check a sign-in with a stored passkey; ``None`` if it fails.

    The library refuses a counter that went backwards (a cloned key) when
    the device keeps one; synced passkeys always report zero.
    """
    data = _parsed(credential)
    if data is None:
        return None
    try:
        verified = verify_authentication_response(
            credential=data,
            expected_challenge=challenge,
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
            credential_public_key=base64url_to_bytes(public_key),
            credential_current_sign_count=sign_count,
            require_user_verification=True,
        )
    except (InvalidAuthenticationResponse, InvalidJSONStructure, ValueError, KeyError, TypeError):
        return None
    return UsedPasskey(
        credential_id=encode(verified.credential_id), new_sign_count=int(verified.new_sign_count)
    )


def clean_label(text: str) -> str:
    """A name the customer gives a passkey ("iPhone", "trabajo"), printable and short."""
    kept = "".join(ch for ch in text if ch.isprintable()).strip()
    return kept[:LABEL_CHARS]


__all__ = [
    "CHALLENGE_MINUTES",
    "COOKIE",
    "MAX_PER_ACCOUNT",
    "MAX_STARTS_PER_HOUR",
    "NewPasskey",
    "RelyingParty",
    "UsedPasskey",
    "authentication_options",
    "clean_label",
    "credential_id",
    "decode",
    "encode",
    "new_challenge",
    "registration_options",
    "relying_party",
    "verify_new",
    "verify_use",
]
