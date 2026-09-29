"""Polish of the account, sign-up and recovery: what a customer-style audit found.

Counters in the singular, reports told apart, an indicator that follows the
rule of the upload, the typo question on the e-mail change, a sign-up limit
that counts sign-ups, more throwaway services, the address as a password,
codes that give no credit, messages that were missing or borrowed, and texts
that no longer say a link was sent when none was.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from test_audit_user_accounts import (  # noqa: E402
    PASSWORD,
    _audit_id,
    _client,
    _csrf,
    _seeded_file,
    _signup,
    _upload,
)

from quant_trade.audit import account_pages, accounts, inbox, strategies  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.store import AccountAudit, AccountRecord  # noqa: E402

LANGUAGES = account_pages.LANGUAGES
ACCOUNT = {"es": "/cuenta", "en": "/account", "pt": "/pt/conta"}
SIGNUP = {"es": "/registro", "en": "/signup", "pt": "/pt/cadastro"}
FORGOT = {"es": "/olvide", "en": "/forgot", "pt": "/pt/esqueci"}
STAMP = "2026-09-29T14:05:33Z"
NEW_KEYS = (
    "wrong_current",
    "reports_one",
    "paid_reports_one",
    "credits_one",
    "credits_buy",
    "upload_audit",
    "welcome_refused_unverified_nomail",
    "code_unusable",
    "buy_final_sale_note",
    "export_not_included",
    "recover_lead_mail",
)


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _audit(audit_id: str, created_at: str = STAMP, *, paid: bool = False) -> AccountAudit:
    return AccountAudit(
        audit_id=audit_id,
        created_at=created_at,
        linked_at=created_at,
        overall_class="D",
        paid=paid,
        paid_at=created_at if paid else None,
        paid_with="code" if paid else "",
        purged=False,
        published=False,
        description="",
    )


def _page(locale: str, **extra: object) -> str:
    values: dict[str, object] = dict(
        locale=locale,
        account=AccountRecord("a1", "ana@example.com", locale, STAMP),
        audits=(),
        codes=(),
        credits=0,
        csrf="test-csrf",
        now=STAMP,
        access_codes=True,
        contact_url="https://wa.me/000",
        price_cents=2900,
        pack_price_cents=6900,
    )
    values.update(extra)
    return account_pages.account_page(**values)  # type: ignore[arg-type]


def _kpis(page: str) -> str:
    return _text(page.split("<div class='acct-kpis'>")[1].split("<section")[0])


def _post_signup(client: TestClient, email: str, password: str = PASSWORD, **extra: str):
    path = extra.pop("path", "/registro")
    headers = {"X-Forwarded-For": extra.pop("ip")} if "ip" in extra else {}
    csrf = _csrf(client.get(path).text)
    return client.post(
        path,
        data={"email": email, "password": password, "csrf": csrf, **extra},
        headers=headers,
        follow_redirects=False,
    )


# -- the new texts -----------------------------------------------------------------
@pytest.mark.parametrize("locale", LANGUAGES)
def test_the_new_texts_exist_in_three_languages_and_pass_the_guard(locale: str) -> None:
    copy = account_pages.COPY[locale]
    for key in NEW_KEYS:
        assert copy[key].strip(), key
        assert not find_claims(copy[key]), key
    # Each language has its own words, except where the two languages agree.
    same = {key for key in NEW_KEYS if copy[key] == account_pages.COPY["es"][key]}
    assert same == (set(NEW_KEYS) if locale == "es" else same & {"credits_buy"})
    assert set(account_pages.COPY[locale]) == set(account_pages.COPY["es"])


# -- C2: one report is "1 Informe" ---------------------------------------------------
@pytest.mark.parametrize(
    ("locale", "one", "many"),
    [
        (
            "es",
            ("1 Crédito disponible.", "1 Informe ", "1 Informe completo "),
            ("2 Créditos disponibles.", "2 Informes ", "2 Informes completos "),
        ),
        (
            "en",
            ("1 Credit available.", "1 Report ", "1 Full report "),
            ("2 Credits available.", "2 Reports ", "2 Full reports "),
        ),
        (
            "pt",
            ("1 Crédito disponível.", "1 Relatório ", "1 Relatório completo "),
            ("2 Créditos disponíveis.", "2 Relatórios ", "2 Relatórios completos "),
        ),
    ],
)
def test_the_counters_are_singular_with_one(
    locale: str, one: tuple[str, ...], many: tuple[str, ...]
) -> None:
    single = re.sub(
        r"\s+", " ", _kpis(_page(locale, credits=1, audits=(_audit("a" * 32, paid=True),)))
    )
    for words in one:
        assert words in single + " ", (words, single)
    two = (_audit("a" * 32, paid=True), _audit("b" * 32, paid=True))
    plural = re.sub(r"\s+", " ", _kpis(_page(locale, credits=2, audits=two)))
    for words in many:
        assert words in plural + " ", (words, plural)
    none = re.sub(r"\s+", " ", _kpis(_page(locale, credits=0)))
    assert many[0][2:] in none and many[1][2:] in none + " "


# -- C3: two reports of the same day -------------------------------------------------
@pytest.mark.parametrize("locale", LANGUAGES)
def test_the_list_shows_the_time_and_the_short_id_of_each_report(locale: str) -> None:
    first = _audit("52d6b8e2" + "0" * 24, "2026-09-29T09:15:00Z")
    second = _audit("9f01c3aa" + "1" * 24, "2026-09-29T14:05:33Z")
    page = _page(locale, audits=(first, second))
    table = page.split("<table class='acct-table acct-reports")[1].split("</table>")[0]
    assert "<td>2026-09-29 <span class='acct-when'>09:15 UTC · 52d6b8e2</span></td>" in table
    assert "<td>2026-09-29 <span class='acct-when'>14:05 UTC · 9f01c3aa</span></td>" in table
    # Only the first 8 characters, as the strategies list shows them.
    assert first.audit_id not in _text(table)
    # A stored date without a time keeps the identifier.
    short = _page(locale, audits=(_audit("abcdef12" + "2" * 24, "2026-09-29"),))
    assert "<span class='acct-when'>abcdef12</span>" in short


def test_the_time_wraps_under_the_date_so_a_phone_does_not_scroll_sideways() -> None:
    css = account_pages.ACCOUNT_CSS
    rule = css.split(".acct-when{")[1].split("}")[0]
    assert "display:block" in rule and "overflow-wrap:anywhere" in rule
    assert "nowrap" not in rule
    # The date cell keeps the column that shrinks on a phone.
    assert ".acct-reports td:nth-child(1){grid-row:1;grid-column:2;" in css
    assert ".acct-reports tr{display:grid;grid-template-columns:auto minmax(0,1fr) auto" in css


# -- C4: the indicator follows the rule of the upload --------------------------------
def test_the_free_report_indicator_follows_the_inbox_rule(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "ana.perez@gmail.com", welcome=True)
    fresh = client.get("/cuenta").text
    assert "acct-gift is-on" in fresh and "Subir mi primer archivo" in fresh
    assert "acct=welcome" in _upload(client).headers["location"]
    account = store.find_account("ana.perez@gmail.com")  # type: ignore[attr-defined]
    store.delete_account(account.id, with_reports=True)  # type: ignore[attr-defined]
    # The same inbox (dots and a +tag) on a new account, from a new browser.
    for locale, email in (
        ("es", "anaperez+otra@gmail.com"),
        ("en", "a.naperez@googlemail.com"),
        ("pt", "anaperez@gmail.com"),
    ):
        again = TestClient(client.app)
        _signup(again, email, welcome=True)
        page = again.get(ACCOUNT[locale]).text
        copy = account_pages.COPY[locale]
        assert "acct-gift is-on" not in page
        assert f"<b>{copy['welcome_available']}</b>" not in page
        assert f"<b>{copy['welcome_used']}</b>" in page
        assert copy["first_audit"] not in page and copy["upload_audit"] in page
    # The upload agrees with the page: a preview, told why.
    refused = again.post(
        "/audits", files=_seeded_file(41), data={"consent": "on"}, follow_redirects=False
    )
    assert "acct=preview_email" in refused.headers["location"]
    # Another person keeps the offer.
    other = TestClient(client.app)
    _signup(other, "bea@gmail.com", welcome=True)
    assert "acct-gift is-on" in other.get("/cuenta").text


# -- C5: the typo question on the e-mail change ---------------------------------------
def _change(client: TestClient, base: str, **data: str):
    csrf = _csrf(client.get(base).text)
    return client.post(
        f"{base}/correo",
        data={"current": PASSWORD, "csrf": csrf, **data},
        follow_redirects=False,
    )


@pytest.mark.parametrize(
    ("locale", "words"),
    [
        ("es", "¿Quisiste decir ana@gmail.com?"),
        ("en", "Did you mean ana@gmail.com?"),
        ("pt", "Você quis dizer ana@gmail.com?"),
    ],
)
def test_changing_the_email_asks_about_a_mistyped_provider(
    tmp_path: Path, locale: str, words: str
) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "old@example.com")
    base = ACCOUNT[locale]
    asked = _change(client, base, email="Ana@gmial.com", email_again="ana@gmial.com")
    assert asked.status_code == 200 and words in asked.text
    assert asked.headers["cache-control"] == "no-store"
    assert f"action='{base}/correo'" in asked.text
    assert "value='ana@gmail.com'" in asked.text
    assert "name='email_as_typed' value='ana@gmial.com'" in asked.text
    assert "name='current'" in asked.text and PASSWORD not in asked.text
    assert not find_claims(_text(asked.text))
    # Nothing changed yet.
    assert store.find_account("old@example.com") is not None  # type: ignore[attr-defined]
    assert store.find_account("ana@gmial.com") is None  # type: ignore[attr-defined]
    # Accepting the correction moves the account to the provider's address.
    fixed = client.post(
        f"{base}/correo",
        data={
            "email": "ana@gmail.com",
            "email_again": "ana@gmail.com",
            "current": PASSWORD,
            "csrf": _csrf(asked.text),
        },
        follow_redirects=False,
    )
    assert fixed.headers["location"] == f"{base}?done=email_changed"
    assert store.find_account("ana@gmail.com") is not None  # type: ignore[attr-defined]


def test_changing_the_email_keeps_the_typed_address_when_the_box_says_so(
    tmp_path: Path,
) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "old@example.com")
    asked = _change(client, "/cuenta", email="bia@hotmal.com", email_again="bia@hotmal.com")
    assert "¿Quisiste decir bia@hotmail.com?" in asked.text
    kept = client.post(
        "/cuenta/correo",
        data={
            "email": "bia@hotmail.com",
            "email_again": "bia@hotmail.com",
            "email_as_typed": "bia@hotmal.com",
            "current": PASSWORD,
            "csrf": _csrf(asked.text),
        },
        follow_redirects=False,
    )
    assert kept.headers["location"] == "/cuenta?done=email_changed"
    assert store.find_account("bia@hotmal.com") is not None  # type: ignore[attr-defined]
    assert store.find_account("bia@hotmail.com") is None  # type: ignore[attr-defined]


def test_the_typo_question_never_skips_the_other_checks(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "old@example.com")
    # Without the password there is no question and no change.
    csrf = _csrf(client.get("/cuenta").text)
    wrong = client.post(
        "/cuenta/correo",
        data={
            "email": "ana@gmial.com",
            "email_again": "ana@gmial.com",
            "current": "otra frase equivocada",
            "csrf": csrf,
        },
        follow_redirects=False,
    )
    assert wrong.headers["location"] == "/cuenta?error=wrong_current"
    # Two different addresses are a mismatch, not a question.
    mismatch = _change(client, "/cuenta", email="ana@gmial.com", email_again="ana@gmail.com")
    assert mismatch.headers["location"] == "/cuenta?error=email_mismatch"
    # The kept address still goes through every check.
    for kept, error in (
        ("ana@mailinator.com", "email_disposable"),
        ("ana luz@gmial.com", "email_bad"),
        ('"ana"@gmial.com', "email_simple"),
        ("old@example.com", "email_same"),
    ):
        refused = _change(
            client,
            "/cuenta",
            email="ana@gmail.com",
            email_again="ana@gmail.com",
            email_as_typed=kept,
        )
        assert refused.headers["location"] == f"/cuenta?error={error}", kept
    # A forged form gets nothing.
    forged = client.post(
        "/cuenta/correo",
        data={"email": "ana@gmial.com", "email_again": "ana@gmial.com", "current": PASSWORD},
        follow_redirects=False,
    )
    assert forged.status_code != 200 or "gmail.com" not in forged.text
    assert store.find_account("old@example.com") is not None  # type: ignore[attr-defined]
    # A known provider is never questioned.
    direct = _change(client, "/cuenta", email="ana@gmail.com", email_again="ana@gmail.com")
    assert direct.headers["location"] == "/cuenta?done=email_changed"


# -- C6: the sign-up limit counts sign-ups --------------------------------------------
def test_form_mistakes_and_the_typo_question_do_not_spend_the_sign_ups(
    tmp_path: Path,
) -> None:
    client, store, _ = _client(tmp_path, trusted_proxy_hops=1)
    ip = "203.0.113.120"
    for password in ("corta", "password2024", "1234567890", "qwertyuiop", "aaaaaaaaaaaa"):
        assert _post_signup(client, "ana@example.com", password, ip=ip).status_code == 400
    for _ in range(accounts.MAX_SIGNUPS_PER_HOUR):
        asked = _post_signup(client, "ana@gmial.com", ip=ip)
        assert asked.status_code == 200 and "Quisiste" in asked.text
    assert _post_signup(client, "no es un correo", ip=ip).status_code == 400
    # After eleven forms sent back, the customer still signs up.
    done = _post_signup(client, "ana@example.com", ip=ip)
    assert done.status_code == 303 and "retry-after" not in done.headers
    assert store.find_account("ana@example.com") is not None  # type: ignore[attr-defined]


@pytest.mark.parametrize("locale", LANGUAGES)
def test_sign_ups_and_taken_addresses_count_and_the_refusal_says_when_to_retry(
    tmp_path: Path, locale: str
) -> None:
    client, store, _ = _client(tmp_path, trusted_proxy_hops=1)
    ip = "203.0.113.121"
    path = SIGNUP[locale]
    assert _post_signup(client, "first@example.com", ip=ip, path=path).status_code == 303
    client.cookies.clear()
    # Asking again and again whether an address has an account is counted.
    for _ in range(accounts.MAX_SIGNUPS_PER_HOUR - 1):
        assert _post_signup(client, "first@example.com", ip=ip, path=path).status_code == 409
    limited = _post_signup(client, "second@example.com", ip=ip, path=path)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == str(accounts.SIGNUP_RETRY_AFTER_SECONDS) == "3600"
    assert account_pages.COPY[locale]["too_many"] in limited.text
    assert store.find_account("second@example.com") is None  # type: ignore[attr-defined]
    # A mistake past the limit gets the same answer, and another network signs up.
    assert _post_signup(client, "x", ip=ip, path=path).status_code == 429
    assert _post_signup(client, "third@example.com", ip="203.0.113.122").status_code == 303


def test_forms_sent_back_have_their_own_higher_ceiling(tmp_path: Path) -> None:
    assert accounts.MAX_INVALID_SIGNUPS_PER_HOUR == 30
    assert accounts.MAX_INVALID_SIGNUPS_PER_HOUR > accounts.MAX_SIGNUPS_PER_HOUR
    client, store, _ = _client(tmp_path, trusted_proxy_hops=1)
    ip = "2001:db8:5:6::"
    for n in range(accounts.MAX_INVALID_SIGNUPS_PER_HOUR):
        sent = _post_signup(client, "ana@example.com", "corta", ip=f"{ip}{n + 1:x}")
        assert sent.status_code == 400, n
    # Past it the form answers 429 before it checks anything, for the whole /64.
    hammered = _post_signup(client, "ana@example.com", "corta", ip=f"{ip}ff")
    assert hammered.status_code == 429 and hammered.headers["retry-after"] == "3600"
    valid = _post_signup(client, "ana@example.com", ip=f"{ip}fe")
    assert valid.status_code == 429 and valid.headers["retry-after"] == "3600"
    assert store.find_account("ana@example.com") is None  # type: ignore[attr-defined]
    # A forged form is refused before anything is counted.
    forged = client.post(
        "/registro",
        data={"email": "a@example.com", "password": PASSWORD, "csrf": "nope"},
        headers={"X-Forwarded-For": "2001:db8:5:7::1"},
    )
    assert forged.status_code == 400
    assert _post_signup(client, "bea@example.com", ip="2001:db8:5:7::2").status_code == 303


# -- C7: throwaway services -----------------------------------------------------------
REPORTED = (
    "grr.la",
    "pokemail.net",
    "mailsac.com",
    "1secmail.com",
    "emailfake.com",
    "minuteinbox.com",
    "mail7.io",
    "correotemporal.org",
    "emailtemporal.org",
    "tempmailaddress.com",
    "fakemailgenerator.com",
    "mytrashmail.com",
    "moakt.cc",
    "tempm.com",
    "cock.li",
    "mailnull.com",
    "trbvm.com",
)
ALIASES = (
    "sharklasers.com",
    "guerrillamail.net",
    "guerrillamail.org",
    "guerrillamail.biz",
    "guerrillamail.de",
    "guerrillamailblock.com",
    "spam4.me",
    "sogetthis.com",
    "binkmail.com",
    "10minutemail.org",
    "temp-mail.ru",
    "cool.fr.nf",
    "1secmail.org",
    "moakt.ws",
)


def test_the_list_of_throwaway_services_covers_the_reported_ones_and_their_aliases() -> None:
    assert len(inbox.DISPOSABLE_DOMAINS) == 110
    for domain in REPORTED + ALIASES:
        assert inbox.is_disposable(f"x@{domain}"), domain
        assert inbox.is_disposable(f"x@mail.{domain}"), domain
    for domain in inbox.DISPOSABLE_DOMAINS:
        assert domain == domain.lower().strip() and "." in domain
        assert accounts.simple_email(f"x@{domain}"), domain
        # No provider a customer really uses, and nothing the typo question suggests.
        assert domain not in inbox.COMMON_PROVIDERS, domain
    for real in ("gmail.com", "outlook.com", "yahoo.com.mx", "uol.com.br", "fr.nf", "empresa.mx"):
        assert not inbox.is_disposable(f"x@{real}"), real


@pytest.mark.parametrize(
    ("locale", "email"),
    [("es", "x@grr.la"), ("en", "x@pokemail.net"), ("pt", "x@moakt.cc"), ("es", "x@1secmail.com")],
)
def test_the_reported_services_cannot_open_an_account(
    tmp_path: Path, locale: str, email: str
) -> None:
    client, store, _ = _client(tmp_path)
    refused = _post_signup(client, email, path=SIGNUP[locale])
    assert refused.status_code == 400
    assert account_pages._e(account_pages.COPY[locale]["email_disposable"]) in refused.text
    assert store.find_account(email) is None  # type: ignore[attr-defined]


# -- C8: the address is not a password ------------------------------------------------
@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("rigor.prueba.clave1990@gmail.com", "rigor.prueba.clave1990"),
        ("rigor.prueba.clave1990@gmail.com", "Rigor.Prueba.Clave1990"),
        ("rigor.prueba.clave1990@gmail.com", "rigorpruebaclave1990"),
        ("rigor.prueba.clave1990@gmail.com", "rigor.prueba.clave"),
        ("rigor.prueba.clave1990@gmail.com", "rigorpruebaclave2026"),
        ("rigor.prueba.clave1990@gmail.com", "rigor.prueba.clave1990@gmail.com"),
        ("rigor.prueba.clave1990@gmail.com", " Rigor.Prueba.Clave1990@GMAIL.com "),
        ("rigor.prueba.clave1990@gmail.com", "rigor-prueba-clave1990 gmail com"),
        ("rigorpruebaclave1991@gmail.com", "rigorpruebaclave1991"),
        ("2024rigorprueba@gmail.com", "2024rigorprueba"),
        ("rigorpruebaclave@gmail.com", "rigorpruebaclave"),
        ("rigorpruebaclave@gmail.com", "rigorpruebaclave2026"),
    ],
)
def test_the_own_address_or_its_name_is_refused_as_password(email: str, password: str) -> None:
    assert accounts.password_problem(password, email=email) == "password_common"


def test_a_password_that_only_shares_words_with_the_address_is_accepted() -> None:
    for email in ("rigor.prueba.clave1990@gmail.com", "ana1990@gmail.com", "12345@example.com"):
        assert accounts.password_problem(PASSWORD, email=email) == ""
        assert accounts.password_problem("caballo-bateria-grapa-correcta", email=email) == ""
    assert accounts.password_problem("rigorpruebaclave1990", email="") == ""
    assert accounts.password_problem("rigorpruebaclave1990") == ""


def test_sign_up_and_the_password_change_refuse_the_own_address(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    email = "rigor.prueba.clave1990@gmail.com"
    for password in ("rigor.prueba.clave1990", email):
        refused = _post_signup(client, email, password)
        assert refused.status_code == 400
        assert account_pages.COPY["es"]["password_common"] in refused.text
    assert store.find_account(email) is None  # type: ignore[attr-defined]
    _signup(client, email)
    csrf = _csrf(client.get("/cuenta").text)
    changed = client.post(
        "/cuenta/contrasena",
        data={"current": PASSWORD, "password": email, "csrf": csrf},
        follow_redirects=False,
    )
    assert changed.headers["location"] == "/cuenta?error=password_common"
    assert accounts.verify_password(store.account_with_hash(email)[1], PASSWORD)  # type: ignore[attr-defined]


# -- C9: a code that gives no credit is not added -------------------------------------
@pytest.mark.parametrize("locale", LANGUAGES)
def test_a_disabled_code_is_not_added_to_the_account(tmp_path: Path, locale: str) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "ana@example.com")
    now = datetime.now(UTC)
    account = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    off, record = store.create_access_code(credits=2, note="", at=now)  # type: ignore[attr-defined]
    assert store.disable_access_code(record.id)  # type: ignore[attr-defined]
    base = ACCOUNT[locale]

    def add(code: str) -> str:
        csrf = _csrf(client.get(base).text)
        sent = client.post(
            f"{base}/codigo", data={"code": code, "csrf": csrf}, follow_redirects=False
        )
        return str(sent.headers["location"])

    assert add(off) == f"{base}?error=code_unusable"
    page = client.get(f"{base}?error=code_unusable").text
    copy = account_pages.COPY[locale]
    assert copy["code_unusable"] in page and copy["code_linked"] not in page
    assert store.account_codes_list(account.id) == []  # type: ignore[attr-defined]
    assert store.account_credits(account.id, now) == 0  # type: ignore[attr-defined]
    # A good code is added as before, and keeps its answers afterwards.
    good, kept = store.create_access_code(credits=1, note="", at=now)  # type: ignore[attr-defined]
    assert add(good) == f"{base}?done=code_linked"
    assert add(good) == f"{base}?error=code_already"
    assert store.account_credits(account.id, now) == 1  # type: ignore[attr-defined]
    assert store.disable_access_code(kept.id)  # type: ignore[attr-defined]
    assert add(good) == f"{base}?error=code_already"
    assert add("AUD-0000-0000-0000") == f"{base}?error=code_unknown"


# -- C10: the messages of "Mis estrategias" -------------------------------------------
@pytest.mark.parametrize("locale", LANGUAGES)
def test_saving_a_strategy_without_a_name_says_what_is_missing(tmp_path: Path, locale: str) -> None:
    client, _, _ = _client(tmp_path)
    _signup(client, "ana@example.com")
    audit_id = _audit_id(_upload(client).headers["location"])
    base = ACCOUNT[locale]
    csrf = _csrf(client.get(base).text)
    sent = client.post(
        f"{account_pages.strategies_path(locale)}/guardar",
        data={"audit_id": audit_id, "strategy": "new", "name": "  ", "csrf": csrf},
        follow_redirects=False,
    )
    assert sent.headers["location"] == f"{base}?error=file_bad#estrategias"
    page = client.get(f"{base}?error=file_bad").text
    words = strategies.COPY[locale]["file_bad"]
    assert f"<div class='error' role='alert'>{account_pages._e(words)}</div>" in page
    full = _page(locale, error="strategy_full")
    assert account_pages._e(strategies.COPY[locale]["strategy_full"]) in full
    assert "<div class='acct-parts has-alert'>" in full
    # Only those two keys are read from the strategies' texts.
    theirs = set(strategies.COPY[locale]) - set(account_pages.COPY[locale])
    assert set(account_pages.STRATEGY_ERRORS) <= theirs
    for other in sorted(theirs - set(account_pages.STRATEGY_ERRORS))[:6]:
        assert "role='alert'" not in _page(locale, error=other), other


# -- C11: the current password has a message of its own -------------------------------
@pytest.mark.parametrize("locale", LANGUAGES)
def test_a_wrong_current_password_is_not_called_a_wrong_email(tmp_path: Path, locale: str) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "ana@example.com")
    base = ACCOUNT[locale]
    copy = account_pages.COPY[locale]
    forms = {
        "/contrasena": ({"password": "otra frase larga distinta"}, ""),
        "/correo": ({"email": "b@example.com", "email_again": "b@example.com"}, ""),
        "/borrar": ({}, ""),
        "/dos-pasos": ({}, "#dos-pasos"),
        "/recuperacion": ({}, "#recuperacion"),
    }
    for action, (fields, anchor) in forms.items():
        csrf = _csrf(client.get(base).text)
        sent = client.post(
            base + action,
            data={"current": "una frase equivocada", "csrf": csrf, **fields},
            follow_redirects=False,
        )
        assert sent.headers["location"] == f"{base}?error=wrong_current{anchor}", action
    page = client.get(f"{base}?error=wrong_current").text
    assert f"<div class='error' role='alert'>{copy['wrong_current']}</div>" in page
    assert copy["wrong"] not in page
    assert store.find_account("ana@example.com") is not None  # type: ignore[attr-defined]
    # Sign-in keeps its own words: it cannot say which of the two was wrong.
    assert copy["wrong"] != copy["wrong_current"]


# -- C12: buying by WhatsApp says the sale is final -----------------------------------
@pytest.mark.parametrize(
    ("locale", "words"),
    [
        ("es", "la compra no es reembolsable"),
        ("en", "the purchase is not refundable"),
        ("pt", "a compra não é reembolsável"),
    ],
)
def test_buying_by_whatsapp_says_the_sale_is_final(locale: str, words: str) -> None:
    copy = account_pages.COPY[locale]
    assert words in copy["buy_final_sale_note"] and words in copy["buy_final_sale"]
    page = _page(locale)
    buy = page.split(f"<h3>{account_pages._e(copy['buy_title'])}</h3>")[1].split("</section>")[0]
    assert "wa.me/000" in buy and "<form" not in buy
    assert f"<p class='muted'>{account_pages._e(copy['buy_final_sale_note'])}</p>" in buy
    assert buy.index(copy["buy_code_wait"][:20]) < buy.index(words)
    # With the card form, its own box says it once.
    card = _page(locale, card_markets=("MX", "US"))
    assert copy["buy_final_sale"] in card and copy["buy_final_sale_note"] not in card
    assert not find_claims(_text(page))


# -- C13: the recovery page names the e-mail link first -------------------------------
@pytest.mark.parametrize("locale", LANGUAGES)
def test_the_recovery_page_introduces_what_it_offers_first(locale: str) -> None:
    copy = account_pages.COPY[locale]
    ready = account_pages.forgot_page(
        locale=locale, contact_url="https://wa.me/1", csrf="c", email_delivery_ready=True
    )
    lead = ready.split("<p class='lead")[1].split("</p>")[0]
    assert account_pages._e(copy["recover_lead_mail"]) in lead
    assert account_pages._e(copy["recover_lead"]) not in ready
    # The order of the introduction is the order of the page.
    assert ready.index(copy["forgot_email_title"]) < ready.index(copy["recover_title"])
    off = account_pages.forgot_page(locale=locale, contact_url="https://wa.me/1", csrf="c")
    assert account_pages._e(copy["recover_lead"]) in off.split("<p class='lead")[1]
    assert account_pages._e(copy["recover_lead_mail"]) not in off
    assert copy["forgot_email_title"] not in off
    for page in (ready, off):
        assert not find_claims(_text(page))


def test_the_recovery_pages_are_served_with_the_introduction_of_their_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_trade.audit.settings import AuditSettings

    client, _, _ = _client(tmp_path)
    for locale, path in FORGOT.items():
        assert account_pages._e(account_pages.COPY[locale]["recover_lead"]) in client.get(path).text
    monkeypatch.setattr(AuditSettings, "email_delivery_ready", property(lambda self: True))
    for locale, path in FORGOT.items():
        page = client.get(path).text
        assert account_pages._e(account_pages.COPY[locale]["recover_lead_mail"]) in page


# -- C14: no link was sent when mail is not ready -------------------------------------
@pytest.mark.parametrize("locale", LANGUAGES)
def test_a_preview_never_says_a_link_was_sent_when_mail_is_not_ready(
    tmp_path: Path, locale: str
) -> None:
    client, store, settings = _client(
        tmp_path, email_verification_required=True, operator_contact="hola@rigor.example"
    )
    assert not settings.email_delivery_ready
    done = _signup(client, "nueva@example.com", welcome=True)
    assert done.headers["location"] == "/cuenta?done=welcome"
    sent = client.post(
        "/audits",
        files=_seeded_file(51),
        data={"consent": "on", "locale": locale},
        follow_redirects=False,
    )
    where = sent.headers["location"]
    assert "acct=preview_unverified" in where
    page = client.get(where).text
    copy = account_pages.COPY[locale]
    honest = copy["welcome_refused_unverified_nomail"].format(contact="hola@rigor.example")
    assert account_pages._e(honest) in page
    assert account_pages._e(copy["welcome_refused_unverified"]) not in page
    assert "{contact}" not in page
    assert not find_claims(honest)
    account = store.find_account("nueva@example.com")  # type: ignore[attr-defined]
    assert not store.welcome_used(account.id)  # type: ignore[attr-defined]


def test_without_a_published_address_the_notice_names_the_contact_page(tmp_path: Path) -> None:
    client, _, _ = _client(
        tmp_path, email_verification_required=True, base_url="https://rigor.example"
    )
    client.base_url = "https://rigor.example"
    _signup(client, "nueva@example.com", welcome=True)
    for locale, contact in (("es", "/contacto"), ("en", "/en/contact"), ("pt", "/pt/contato")):
        sent = client.post(
            "/audits",
            files=_seeded_file(60 + len(locale + contact)),
            data={"consent": "on", "locale": locale},
            follow_redirects=False,
        )
        page = client.get(sent.headers["location"]).text
        assert f": https://rigor.example{contact}" in page, locale
        assert client.get(contact).status_code == 200


def test_with_mail_ready_the_preview_keeps_the_text_about_the_link(tmp_path: Path) -> None:
    client, _, settings = _client(
        tmp_path,
        base_url="https://rigor.example",
        email_verification_required=True,
        email_token_secret="stable secret shared across replicas 1234567890",
        resend_api_key="re_test_0123456789abcdefghij",
        smtp_from="Rigor <hola@example.com>",
    )
    client.base_url = "https://rigor.example"
    assert settings.email_delivery_ready
    _signup(client, "nueva@example.com", welcome=True)
    sent = client.post(
        "/audits", files=_seeded_file(52), data={"consent": "on"}, follow_redirects=False
    )
    page = client.get(sent.headers["location"]).text
    assert account_pages._e(account_pages.COPY["es"]["welcome_refused_unverified"]) in page
    assert "no está disponible en este momento" not in page


# -- C15: the note of the data download -----------------------------------------------
@pytest.mark.parametrize(
    ("locale", "words"),
    [
        ("es", "No se incluyen: tu contraseña"),
        ("en", "Your password (kept only as a scrypt hash)"),
        ("pt", "Não estão incluídos: sua senha"),
    ],
)
def test_the_data_download_note_follows_the_language(
    tmp_path: Path, locale: str, words: str
) -> None:
    client, _, _ = _client(tmp_path)
    _signup(client, "ana@example.com")
    answer = client.get(f"{ACCOUNT[locale]}/datos")
    assert answer.status_code == 200
    data = json.loads(answer.text)
    assert data["not_included"] == account_pages.COPY[locale]["export_not_included"]
    assert data["not_included"].startswith(words) and "Stripe" in data["not_included"]
    # The keys of the file stay the same in every language.
    assert {"service", "exported_at", "not_included", "account", "reports"} <= set(data)
