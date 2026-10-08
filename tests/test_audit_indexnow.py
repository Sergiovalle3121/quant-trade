"""IndexNow: the key file, the key setting, the submission and the command, all offline."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from quant_trade.audit import indexnow, seo  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import SECURITY_HEADERS, create_app  # noqa: E402
from quant_trade.cli import app  # noqa: E402

runner = CliRunner()
HOST = "rigorscore.com"
SITE = f"https://{HOST}"
KEY = indexnow.INDEXNOW_KEY
LOCATION = f"{SITE}/{KEY}.txt"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any real HTTP request fails the test; only ``httpx.MockTransport`` answers."""

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("a test tried to reach the network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    monkeypatch.delenv("AUDIT_INDEXNOW_KEY", raising=False)


def _client(tmp_path: Path, **env: str) -> TestClient:
    settings = AuditSettings.from_env({"DATABASE_URL": f"sqlite:///{tmp_path}/audit.db", **env})
    return TestClient(
        create_app(settings, make_store(settings.database_url)), raise_server_exceptions=False
    )


class Recorder:
    """A mock IndexNow that answers ``statuses`` in turn and keeps every request."""

    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses) or [200]
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self.statuses[min(len(self.requests), len(self.statuses)) - 1]
        return httpx.Response(status, text="")

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def bodies(self) -> list[dict[str, object]]:
        return [json.loads(request.content.decode("utf-8")) for request in self.requests]


def _submit(urls: list[str], recorder: Recorder) -> indexnow.Submission:
    with recorder.client() as client:
        return indexnow.submit(urls, host=HOST, key=KEY, key_location=LOCATION, client=client)


# -- the key file ----------------------------------------------------------------


def test_the_key_file_answers_the_exact_key_and_no_other_txt_exists(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get(f"/{KEY}.txt")
    assert response.status_code == 200
    assert response.content == KEY.encode("utf-8")
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    for other in ("/other.txt", f"/{KEY[:-1]}.txt", "/llms.txt", f"/{KEY}.txt.txt"):
        assert client.get(other).status_code == 404, other


def test_the_key_file_is_neither_listed_nor_closed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    path = f"/{KEY}.txt"
    assert KEY not in client.get("/sitemap.xml").text
    assert KEY not in seo.sitemap_xml(SITE)
    robots = client.get("/robots.txt").text
    disallowed = [
        line.split(":", 1)[1].strip()
        for line in robots.splitlines()
        if line.startswith("Disallow:")
    ]
    assert disallowed and not [rule for rule in disallowed if path.startswith(rule)]
    assert not seo.is_private_path(path)
    assert "X-Robots-Tag" not in client.get(path).headers


def test_an_override_key_moves_the_file(tmp_path: Path) -> None:
    client = _client(tmp_path, AUDIT_INDEXNOW_KEY="Rigor-key-2026")
    response = client.get("/Rigor-key-2026.txt")
    assert response.status_code == 200
    assert response.text == "Rigor-key-2026"
    assert client.get(f"/{KEY}.txt").status_code == 404


# -- the key setting -------------------------------------------------------------


def test_a_valid_variable_replaces_the_constant_and_an_invalid_one_does_not() -> None:
    assert AuditSettings().indexnow_key == KEY
    assert AuditSettings.from_env({}).indexnow_key == KEY
    for good in ("abcd1234", " Rigor-key-2026 ", "A" * 128, "0123456789abcdef0123456789abcdef"):
        assert AuditSettings.from_env({"AUDIT_INDEXNOW_KEY": good}).indexnow_key == good.strip()
    bad_keys = ("", "   ", "short12", "A" * 129, "bad key!", "../etc/passwd", "key_with_us")
    for bad in (*bad_keys, "ключ1234"):
        assert AuditSettings.from_env({"AUDIT_INDEXNOW_KEY": bad}).indexnow_key == KEY, bad


# -- the submission --------------------------------------------------------------


def test_submit_keeps_https_urls_on_the_host_once_and_sends_the_exact_json() -> None:
    recorder = Recorder(200)
    urls = [
        f"{SITE}/a",
        f"http://{HOST}/b",
        f"https://www.{HOST}/c",
        "https://other.example/d",
        f"{SITE}/a",
        f"https://{HOST}:443/e",
        f"ftp://{HOST}/f",
        f"{SITE}/x y",
        f"https://user@{HOST}/h",
        f"{SITE}/g",
    ]
    result = _submit(urls, recorder)
    assert result.dropped == 7
    assert result.duplicates == 1
    assert [(batch.urls, batch.status, batch.accepted) for batch in result.batches] == [
        (2, 200, True)
    ]
    assert result.sent == 2 and result.accepted
    [request] = recorder.requests
    assert request.method == "POST"
    assert str(request.url) == "https://api.indexnow.org/indexnow"
    assert request.headers["content-type"] == "application/json; charset=utf-8"
    body = json.loads(request.content.decode("utf-8"))
    assert list(body) == ["host", "key", "keyLocation", "urlList"]
    assert body == {
        "host": HOST,
        "key": KEY,
        "keyLocation": LOCATION,
        "urlList": [f"{SITE}/a", f"{SITE}/g"],
    }


def test_submit_sends_at_most_ten_thousand_urls_per_batch() -> None:
    recorder = Recorder(200, 202)
    urls = [f"{SITE}/page-{number}" for number in range(10_001)]
    result = _submit(urls, recorder)
    assert [len(body["urlList"]) for body in recorder.bodies()] == [10_000, 1]  # type: ignore[arg-type]
    assert recorder.bodies()[1]["urlList"] == [f"{SITE}/page-10000"]
    assert [(batch.urls, batch.status) for batch in result.batches] == [(10_000, 200), (1, 202)]
    assert result.accepted and result.sent == 10_001


@pytest.mark.parametrize(
    ("status", "accepted", "name"),
    [
        (200, True, "OK"),
        (202, True, "Accepted"),
        (400, False, "Bad request"),
        (403, False, "Forbidden"),
        (422, False, "Unprocessable Entity"),
        (429, False, "Too Many Requests"),
        (500, False, "unexpected answer (HTTP 500)"),
    ],
)
def test_each_documented_answer_is_named(status: int, accepted: bool, name: str) -> None:
    result = _submit([f"{SITE}/"], Recorder(status))
    [batch] = result.batches
    assert batch.status == status
    assert batch.accepted is accepted
    assert result.accepted is accepted
    assert batch.meaning.startswith(name)
    assert find_claims(batch.meaning) == []


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
def test_a_network_failure_is_an_error_without_its_details(error: type[Exception]) -> None:
    secret = f"secret {SITE}/a {KEY}"

    def fail(request: httpx.Request) -> httpx.Response:
        raise error(secret, request=request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        result = indexnow.submit(
            [f"{SITE}/a"], host=HOST, key=KEY, key_location=LOCATION, client=client
        )
    [batch] = result.batches
    assert batch.status is None and not batch.accepted and not result.accepted
    assert error.__name__ in batch.meaning
    assert "secret" not in batch.meaning and KEY not in batch.meaning


def test_nothing_is_sent_when_no_url_is_left() -> None:
    recorder = Recorder(200)
    result = _submit([f"http://{HOST}/", "https://other.example/"], recorder)
    assert recorder.requests == []
    assert result.batches == () and result.dropped == 2 and result.sent == 0


def test_submit_opens_and_closes_its_own_client(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder(202)
    opened: list[httpx.Client] = []

    def new_client() -> httpx.Client:
        opened.append(recorder.client())
        return opened[-1]

    monkeypatch.setattr(indexnow, "_new_client", new_client)
    result = indexnow.submit([f"{SITE}/"], host=HOST, key=KEY, key_location=LOCATION)
    assert result.accepted and len(recorder.requests) == 1
    assert len(opened) == 1 and opened[0].is_closed


def test_submit_refuses_a_bad_key_host_or_key_location() -> None:
    recorder = Recorder(200)
    with recorder.client() as client:
        for kwargs in (
            {"host": HOST, "key": "bad key", "key_location": LOCATION},
            {"host": "", "key": KEY, "key_location": LOCATION},
            {"host": f"{HOST}/x", "key": KEY, "key_location": LOCATION},
            {"host": HOST, "key": KEY, "key_location": f"http://{HOST}/{KEY}.txt"},
            {"host": HOST, "key": KEY, "key_location": f"https://other.example/{KEY}.txt"},
        ):
            with pytest.raises(ValueError):
                indexnow.submit([f"{SITE}/"], client=client, **kwargs)
    assert recorder.requests == []


def test_the_site_must_be_an_https_root() -> None:
    assert indexnow.site_host("https://RigorScore.com/") == HOST
    for bad in ("http://rigorscore.com", "rigorscore.com", "https://rigorscore.com/en", "https://"):
        with pytest.raises(ValueError):
            indexnow.site_host(bad)


def test_the_sitemap_urls_are_the_sitemap_locations() -> None:
    urls = indexnow.sitemap_urls(SITE)
    expected = {f"{SITE}{path}" for pair in seo.PUBLIC_PAGES for path in pair.values()}
    assert set(urls) == expected
    assert len(urls) == len(expected)


# -- the command -----------------------------------------------------------------


def _plain(output: str) -> str:
    return ANSI.sub("", output)


def test_the_dry_run_lists_the_sitemap_without_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(*_: object, **__: object) -> None:
        raise AssertionError("the dry run tried to send")

    monkeypatch.setattr(indexnow, "submit", never)
    monkeypatch.setattr(indexnow, "_new_client", never)
    result = runner.invoke(app, ["audit", "indexnow", "--site", SITE, "--dry-run"])
    output = _plain(result.output)
    assert result.exit_code == 0, output
    urls = indexnow.sitemap_urls(SITE)
    assert f"{len(urls)} URL(s) in 1 batch(es) would be sent; nothing was sent" in output
    assert f"Key file: {LOCATION}" in output
    listed = [line.strip() for line in output.splitlines() if line.startswith("  https://")]
    assert listed == urls[:5]
    assert find_claims(output) == []


def test_the_default_site_is_rigorscore(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indexnow, "_new_client", lambda: pytest.fail("network"))
    result = runner.invoke(app, ["audit", "indexnow", "--dry-run"])
    assert result.exit_code == 0
    assert f"IndexNow dry run for {HOST}:" in _plain(result.output)


def test_the_command_sends_the_sitemap_and_prints_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder(202)
    monkeypatch.setattr(indexnow, "_new_client", recorder.client)
    monkeypatch.setenv("AUDIT_INDEXNOW_KEY", "Rigor-key-2026")
    result = runner.invoke(app, ["audit", "indexnow"])
    output = _plain(result.output)
    assert result.exit_code == 0, output
    [body] = recorder.bodies()
    assert body["key"] == "Rigor-key-2026"
    assert body["keyLocation"] == f"{SITE}/Rigor-key-2026.txt"
    assert body["urlList"] == indexnow.sitemap_urls(SITE)
    assert "HTTP 202, Accepted" in output
    assert find_claims(output) == []


@pytest.mark.parametrize("status", [403, 429])
def test_a_refused_batch_fails_the_command(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    monkeypatch.setattr(indexnow, "_new_client", Recorder(status).client)
    result = runner.invoke(app, ["audit", "indexnow"])
    output = _plain(result.output)
    assert result.exit_code == 1
    assert f"HTTP {status}" in output
    assert find_claims(output) == []


def test_a_bad_site_is_refused_before_anything_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indexnow, "_new_client", lambda: pytest.fail("network"))
    result = runner.invoke(app, ["audit", "indexnow", "--site", "http://rigorscore.com"])
    assert result.exit_code == 2
    assert find_claims(_plain(result.output)) == []


def test_the_command_help_passes_the_guard() -> None:
    result = runner.invoke(app, ["audit", "indexnow", "--help"])
    assert result.exit_code == 0, result.output
    # A colour terminal (the CI runner) wraps the help in ANSI codes; read the plain text.
    plain = _plain(result.output)
    for option in ("--site", "--dry-run"):
        assert option in plain
    assert find_claims(plain) == []
