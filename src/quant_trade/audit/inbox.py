"""One free first report per inbox: the address in its basic form.

Mail providers deliver ``Ana.Perez+rigor@gmail.com`` to the same inbox as
``anaperez@gmail.com``. The free first full report is counted against a
SHA-256 of the basic form, so a second account on the same inbox is not a
second person. Throwaway-inbox services are refused at sign-up, because an
address that vanishes in ten minutes cannot hold an account.

The list is short on purpose: the best-known public services, checked by
exact domain or a parent domain. It is not a promise to catch every one.
"""

from __future__ import annotations

import hashlib

#: Providers that ignore dots in the local part.
DOTLESS_DOMAINS = frozenset({"gmail.com"})
#: Domain aliases that reach the same inbox.
DOMAIN_ALIASES = {"googlemail.com": "gmail.com"}

#: Well-known disposable-inbox services (and their common mirror domains).
DISPOSABLE_DOMAINS = frozenset(
    {
        "10minutemail.com",
        "10minutemail.net",
        "20minutemail.com",
        "33mail.com",
        "anonaddy.me",
        "burnermail.io",
        "discard.email",
        "dispostable.com",
        "dropmail.me",
        "emailondeck.com",
        "fakeinbox.com",
        "fakemail.net",
        "getairmail.com",
        "getnada.com",
        "guerrillamail.biz",
        "guerrillamail.com",
        "guerrillamail.de",
        "guerrillamail.info",
        "guerrillamail.net",
        "guerrillamail.org",
        "guerrillamailblock.com",
        "harakirimail.com",
        "inboxbear.com",
        "inboxkitten.com",
        "mail.tm",
        "mail-temp.com",
        "mailcatch.com",
        "maildrop.cc",
        "mailinator.com",
        "mailinator.net",
        "mailinator2.com",
        "mailnesia.com",
        "mailpoof.com",
        "mintemail.com",
        "mohmal.com",
        "moakt.com",
        "mytemp.email",
        "nada.email",
        "sharklasers.com",
        "spam4.me",
        "spamgourmet.com",
        "temp-mail.io",
        "temp-mail.org",
        "tempail.com",
        "tempmail.com",
        "tempmail.dev",
        "tempmail.net",
        "tempmailo.com",
        "tempr.email",
        "throwawaymail.com",
        "tmail.ws",
        "tmpmail.net",
        "tmpmail.org",
        "trashmail.com",
        "trashmail.de",
        "trashmail.net",
        "yopmail.com",
        "yopmail.fr",
        "yopmail.net",
    }
)


def _split(email: str) -> tuple[str, str]:
    local, _, domain = email.strip().lower().rpartition("@")
    return local, domain.rstrip(".")


def basic_form(email: str) -> str:
    """Lower case, no ``+tag``, and no dots where the provider ignores them."""
    local, domain = _split(email)
    domain = DOMAIN_ALIASES.get(domain, domain)
    local = local.split("+", 1)[0]
    if domain in DOTLESS_DOMAINS:
        local = local.replace(".", "")
    return f"{local}@{domain}"


def welcome_key(email: str) -> str:
    """The free-claim key that marks this inbox's free first report as taken."""
    digest = hashlib.sha256(basic_form(email).encode("utf-8")).hexdigest()
    return f"welcome:inbox:{digest}"


def is_disposable(email: str) -> bool:
    """True when the domain, or a domain above it, is a throwaway service."""
    _, domain = _split(email)
    labels = domain.split(".")
    return any(".".join(labels[i:]) in DISPOSABLE_DOMAINS for i in range(len(labels) - 1))
