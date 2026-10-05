"""Search-engine ownership checks served from the owner's variables."""

from __future__ import annotations

import pytest

from quant_trade.audit.settings import AuditSettings

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.web import create_app  # noqa: E402

GOOGLE = "google1a2b3c4d5e6f7a8b.html"
BING = "0123456789ABCDEF0123456789ABCDEF"


def test_variables_are_read_and_anything_else_is_ignored() -> None:
    settings = AuditSettings.from_env(
        {"AUDIT_GOOGLE_VERIFICATION_FILE": f" /{GOOGLE} ", "AUDIT_BING_SITE_AUTH": BING.lower()}
    )
    assert settings.google_verification_file == GOOGLE
    assert settings.bing_site_auth == BING
    for bad in ("../etc/passwd", "google.html", "googleXYZ.html", "index.html", "audits/x"):
        assert (
            AuditSettings.from_env({"AUDIT_GOOGLE_VERIFICATION_FILE": bad}).google_verification_file
            == ""
        )
    for bad in ("short", BING + "0", "<user>x</user>"):
        assert AuditSettings.from_env({"AUDIT_BING_SITE_AUTH": bad}).bing_site_auth == ""


def test_files_are_served_only_when_set() -> None:
    unset = TestClient(create_app(AuditSettings()))
    assert unset.get(f"/{GOOGLE}").status_code == 404
    assert unset.get("/BingSiteAuth.xml").status_code == 404

    client = TestClient(
        create_app(AuditSettings(google_verification_file=GOOGLE, bing_site_auth=BING))
    )
    google = client.get(f"/{GOOGLE}")
    assert google.status_code == 200
    assert google.text == f"google-site-verification: {GOOGLE}"
    bing = client.get("/BingSiteAuth.xml")
    assert bing.status_code == 200
    assert bing.headers["content-type"].startswith("application/xml")
    assert f"<user>{BING}</user>" in bing.text
    assert client.get("/google0000000000000000.html").status_code == 404
