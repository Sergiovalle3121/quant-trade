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
from collections.abc import Callable

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


#: Domains no one can receive mail at (RFC 2606 and RFC 6761).
RESERVED_DOMAINS = frozenset({"example.com", "example.net", "example.org"})
RESERVED_SUFFIXES = (".example", ".test", ".invalid", ".localhost", ".local")


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


def is_reserved(email: str) -> bool:
    """True for documentation and test domains that never receive mail."""
    _, domain = _split(email)
    labels = domain.split(".")
    parents = {".".join(labels[i:]) for i in range(len(labels))}
    return bool(parents & RESERVED_DOMAINS) or ("." + domain).endswith(RESERVED_SUFFIXES)


#: Seconds a sign-up waits on DNS before it gives the address the benefit of the doubt.
DNS_LIFETIME_SECONDS = 3.0

#: ``resolve(domain, record_type)`` returns the record texts, ``[]`` when the
#: name exists without that record, and raises :class:`LookupError` when the
#: name does not exist. Any other exception means "could not tell".
Resolver = Callable[[str, str], list[str]]


def _dns_resolve(domain: str, record_type: str) -> list[str]:
    import dns.exception
    import dns.resolver

    try:
        answer = dns.resolver.resolve(domain, record_type, lifetime=DNS_LIFETIME_SECONDS)
    except dns.resolver.NXDOMAIN as exc:
        raise LookupError(domain) from exc
    except dns.resolver.NoAnswer:
        return []
    except dns.exception.DNSException as exc:
        raise OSError(str(exc)) from exc
    return [record.to_text() for record in answer]


def domain_takes_mail(email: str, *, resolve: Resolver | None = None) -> bool:
    """False only when DNS says the address's domain cannot receive mail.

    A domain takes mail through its MX records or, with none, through its
    A/AAAA address (RFC 5321 §5.1). A single null MX (``0 .``, RFC 7505)
    declares that it takes none. A domain that does not exist takes none.
    Timeouts, a missing resolver library and any other DNS trouble count
    as "takes mail": a customer is never refused because DNS was slow.
    """
    _, domain = _split(email)
    if not domain:
        return False
    try:
        if resolve is None:
            import dns.resolver  # noqa: F401 - only to know whether it is installed

            resolve = _dns_resolve
        mx = resolve(domain, "MX")
        if mx:
            exchanges = {record.split()[-1].rstrip(".") for record in mx}
            return exchanges != {""}
        return any(resolve(domain, kind) for kind in ("A", "AAAA"))
    except LookupError:
        return False
    except Exception:  # noqa: BLE001 - DNS trouble never refuses a customer
        return True
