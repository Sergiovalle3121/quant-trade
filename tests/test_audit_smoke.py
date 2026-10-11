"""Production smoke checks use only local, deterministic HTTP transports."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace
from xml.sax.saxutils import escape

import pytest

pytest.importorskip("httpx")
import httpx  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from quant_trade.audit import pages, seo, smoke  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.cli import app  # noqa: E402

SITE = "https://rigorscore.com"
runner = CliRunner()


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse_network(*_: object, **__: object) -> None:
        raise AssertionError("smoke tests must never reach the network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse_network)
    monkeypatch.setattr(seo, "PUBLIC_PAGES", ())


def sitemap(*paths: str) -> httpx.Response:
    locations = "".join(f"<url><loc>{escape(SITE + path)}</loc></url>" for path in paths)
    return httpx.Response(
        200,
        text=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locations}</urlset>',
        headers={"content-type": "application/xml"},
    )


def html(body: str = "") -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})


class Site:
    def __init__(self, routes: dict[str, httpx.Response]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []
        self.lock = Lock()

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "rigorscore.com", "an external URL was followed"
        assert request.method == "GET"
        assert request.headers["user-agent"] == "RigorSmoke/1.0"
        with self.lock:
            self.requests.append(request)
        path = request.url.raw_path.decode("ascii")
        assert path in self.routes, f"unexpected request: {request.url}"
        return self.routes[path]

    def client(self, *, follow_redirects: bool = False) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(self.handle), follow_redirects=follow_redirects
        )

    def counts(self) -> Counter[str]:
        return Counter(str(request.url) for request in self.requests)


def test_checks_union_of_sitemap_and_public_pages_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seo, "PUBLIC_PAGES", ({"es": "/", "en": "/en"},))
    site = Site(
        {
            "/sitemap.xml": sitemap("/", "/only-sitemap", "/"),
            "/": html("<p>Español</p>"),
            "/en": html(),
            "/only-sitemap": html(),
        }
    )
    with site.client() as client:
        report = smoke.run_smoke(SITE, client=client)
        assert not client.is_closed, "a caller-owned client must remain open"

    assert report.ok and not report.failures
    assert site.counts() == Counter({SITE + path: 1 for path in site.routes})
    assert report.summary == {
        "total": 4,
        "ok": 4,
        "non_200": 0,
        "slow": 0,
        "broken_images": 0,
        "broken_links": 0,
    }
    root = next(item for item in report.requests if item.url == SITE + "/")
    assert root.status == 200
    assert root.size_bytes == len("<p>Español</p>".encode())
    assert root.elapsed_seconds >= 0
    assert root.content_type.startswith("text/html")
    assert not root.error
    assert json.loads(json.dumps(report.to_dict()))["summary"] == report.summary


def test_broken_links_and_html_images_keep_every_referring_page() -> None:
    shared = """
        <a href='/missing#one'>broken</a><a href='/missing#two'>duplicate</a>
        <meta property='og:image' content='/card.png'>
        <meta name='twitter:image' content='/card.png'>
    """
    site = Site(
        {
            "/sitemap.xml": sitemap("/", "/en"),
            "/": html(shared),
            "/en": html(shared),
            "/missing": httpx.Response(404),
            "/card.png": html("This is an error page, not a PNG"),
        }
    )
    with site.client() as client:
        report = smoke.run_smoke(SITE, client=client)

    assert not report.ok
    assert site.counts()[SITE + "/missing"] == 1
    assert site.counts()[SITE + "/card.png"] == 1
    for path in ("/missing", "/card.png"):
        failures = [failure for failure in report.failures if failure.url == SITE + path]
        assert {failure.source for failure in failures} == {SITE + "/", SITE + "/en"}
        assert all(failure.reason for failure in failures)
    assert report.summary["broken_images"] == 1
    assert report.summary["broken_links"] == 1
    assert report.summary["non_200"] == 1


def test_canonical_hreflang_and_nested_links_are_checked() -> None:
    site = Site(
        {
            "/sitemap.xml": sitemap("/"),
            "/": html(
                "<link rel='canonical' href='/canonical'>"
                "<link rel='alternate' hreflang='en' href='/english'>"
                "<a href='/nested'>nested</a>"
            ),
            "/canonical": httpx.Response(404),
            "/english": httpx.Response(503),
            "/nested": html("<a href='/deeper'>deeper</a>"),
            "/deeper": httpx.Response(410),
        }
    )
    with site.client() as client:
        report = smoke.run_smoke(SITE, only="links", client=client)

    assert not report.ok
    assert {(failure.source, failure.url) for failure in report.failures} == {
        (SITE + "/", SITE + "/canonical"),
        (SITE + "/", SITE + "/english"),
        (SITE + "/nested", SITE + "/deeper"),
    }
    assert report.summary["broken_links"] == 3


def test_fragments_host_case_default_ports_and_queries_are_normalized() -> None:
    site = Site(
        {
            "/sitemap.xml": sitemap("/"),
            "/": html(
                "<a href='#section'>same page</a>"
                "<a href='https://RIGORSCORE.COM:443/shared#one'>first</a>"
                "<a href='//rigorscore.com/shared#two'>second</a>"
                "<a href='/shared?q=one&amp;n=2'>query</a>"
            ),
            "/shared": html(),
            "/shared?q=one&n=2": html(),
        }
    )
    with site.client() as client:
        report = smoke.run_smoke("https://RIGORSCORE.COM:443/", client=client)
    assert report.ok
    assert site.counts() == Counter({SITE + path: 1 for path in site.routes})


def test_external_references_are_reported_without_requests() -> None:
    external = {
        "https://external.example/guide",
        "https://cdn.example/card.png",
        "https://external.example/canonical",
        "http://rigorscore.com/insecure",
        "https://rigorscore.com:444/other-port",
    }
    site = Site(
        {
            "/sitemap.xml": sitemap("/"),
            "/": html(
                "<a href='https://external.example/guide'>guide</a>"
                "<meta property='og:image' content='//cdn.example/card.png'>"
                "<link rel='canonical' href='https://external.example/canonical'>"
                "<a href='http://rigorscore.com/insecure'>http</a>"
                "<a href='https://rigorscore.com:444/other-port'>port</a>"
                "<a href='mailto:hello@example.com'>mail</a>"
                "<a href='javascript:alert(1)'>script</a>"
            ),
        }
    )
    with site.client() as client:
        report = smoke.run_smoke(SITE, client=client)
    assert report.ok
    assert external <= {reference.url for reference in report.external}
    assert all(reference.source == SITE + "/" for reference in report.external)
    assert len(site.requests) == 2


@pytest.mark.parametrize(
    "content_type", ["image/png", "IMAGE/PNG; charset=binary", "image/svg+xml"]
)
def test_png_and_svg_card_mime_types_are_accepted(content_type: str) -> None:
    site = Site(
        {
            "/sitemap.xml": sitemap("/"),
            "/": html("<meta property='og:image' content='/card'>"),
            "/card": httpx.Response(200, content=b"image", headers={"content-type": content_type}),
        }
    )
    with site.client() as client:
        report = smoke.run_smoke(SITE, client=client)
    assert report.ok and report.summary["broken_images"] == 0


@pytest.mark.parametrize("status", [404, 500])
def test_image_requires_200_even_with_a_png_mime_type(status: int) -> None:
    site = Site(
        {
            "/sitemap.xml": sitemap("/"),
            "/": html("<meta name='twitter:image' content='/card'>"),
            "/card": httpx.Response(status, headers={"content-type": "image/png"}),
        }
    )
    with site.client() as client:
        report = smoke.run_smoke(SITE, client=client)
    assert not report.ok
    assert report.summary["broken_images"] == 1
    assert any(failure.source == SITE + "/" for failure in report.failures)


@pytest.mark.parametrize(
    ("only", "extra_paths"),
    [("sitemap", set()), ("links", {"/link"}), ("images", {"/card"}), ("all", {"/link", "/card"})],
)
def test_only_limits_reference_checks(only: str, extra_paths: set[str]) -> None:
    site = Site(
        {
            "/sitemap.xml": sitemap("/"),
            "/": html("<a href='/link'>link</a><meta property='og:image' content='/card'>"),
            "/link": html(),
            "/card": httpx.Response(200, headers={"content-type": "image/png"}),
        }
    )
    with site.client() as client:
        report = smoke.run_smoke(SITE, only=only, client=client)
    assert report.ok
    assert {request.url.path for request in site.requests} == {"/sitemap.xml", "/", *extra_paths}


def test_sitemap_indexes_are_checked_once_and_stay_on_origin() -> None:
    site = Site(
        {
            "/sitemap.xml": httpx.Response(
                200,
                text=(
                    "<sitemapindex>"
                    f"<sitemap><loc>{SITE}/child.xml</loc></sitemap>"
                    f"<sitemap><loc>{SITE}/child.xml</loc></sitemap>"
                    "<sitemap><loc>https://outside.example/map.xml</loc></sitemap>"
                    "</sitemapindex>"
                ),
            ),
            "/child.xml": sitemap("/gone"),
            "/gone": httpx.Response(404),
        }
    )
    with site.client() as client:
        report = smoke.run_smoke(SITE, only="sitemap", client=client)
    assert not report.ok
    assert site.counts()[SITE + "/child.xml"] == 1
    assert any(
        failure.source == SITE + "/child.xml" and failure.url == SITE + "/gone"
        for failure in report.failures
    )
    assert any(reference.url == "https://outside.example/map.xml" for reference in report.external)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404),
        httpx.Response(200, text="<html>not a sitemap</html>"),
        httpx.Response(200, text="<urlset><broken>"),
        httpx.Response(200, content=b'<?xml version="1.0" encoding="not-a-codec"?><urlset/>'),
    ],
)
def test_sitemap_failure_does_not_skip_known_public_pages(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    monkeypatch.setattr(seo, "PUBLIC_PAGES", ({"es": "/"},))
    site = Site({"/sitemap.xml": response, "/": html()})
    with site.client() as client:
        report = smoke.run_smoke(SITE, only="sitemap", client=client)
    assert not report.ok
    assert site.counts()[SITE + "/"] == 1
    assert any(failure.url == SITE + "/sitemap.xml" for failure in report.failures)


def test_invalid_html_is_reported_and_other_pages_are_still_parsed() -> None:
    site = Site(
        {
            "/sitemap.xml": sitemap("/broken", "/ok"),
            "/broken": html("<![broken]>"),
            "/ok": html("<a href='/next'>next page</a>"),
            "/next": html(),
        }
    )
    with site.client() as client:
        report = smoke.run_smoke(SITE, client=client)
    assert not report.ok
    assert site.counts()[SITE + "/ok"] == 1
    assert site.counts()[SITE + "/next"] == 1
    assert len(report.failures) == 1
    failure = report.failures[0]
    assert failure.source == failure.url == SITE + "/broken"
    assert failure.kind == "html" and failure.reason


def test_redirects_are_failures_and_are_never_followed() -> None:
    site = Site(
        {
            "/sitemap.xml": sitemap("/"),
            "/": html("<a href='/moved'>moved</a>"),
            "/moved": httpx.Response(302, headers={"location": "https://outside.example/"}),
        }
    )
    with site.client(follow_redirects=True) as client:
        report = smoke.run_smoke(SITE, client=client)
    assert not report.ok and report.summary["broken_links"] == 1
    assert len(site.requests) == 3
    assert any(item.url == SITE + "/moved" and item.status == 302 for item in report.requests)


def test_timeout_is_reported_once_and_other_pages_still_run() -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/sitemap.xml":
            return sitemap("/timeout", "/ok")
        if request.url.path == "/timeout":
            raise httpx.ReadTimeout("connection failed", request=request)
        assert request.url.path == "/ok"
        return html()

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        report = smoke.run_smoke(SITE, timeout=0.25, client=client)
    assert not report.ok
    assert Counter(seen) == Counter({"/sitemap.xml": 1, "/timeout": 1, "/ok": 1})
    failure = next(item for item in report.requests if item.url == SITE + "/timeout")
    assert failure.status is None and failure.error
    assert report.summary["non_200"] == 1


def test_slow_summary_uses_strict_three_second_threshold_without_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter([0.0, 3.0, 10.0, 13.1])
    monkeypatch.setattr(smoke, "time", SimpleNamespace(perf_counter=lambda: next(times)))
    site = Site({"/sitemap.xml": sitemap("/"), "/": html()})
    with site.client() as client:
        report = smoke.run_smoke(SITE, concurrency=1, client=client)
    assert report.ok and report.summary["slow"] == 1
    assert sorted(item.elapsed_seconds for item in report.requests) == pytest.approx([3.0, 3.1])


def test_concurrency_is_bounded_without_serializing_all_pages() -> None:
    barrier = Barrier(2)
    lock = Lock()
    active = 0
    peak = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        if request.url.path == "/sitemap.xml":
            return sitemap("/a", "/b", "/c", "/d")
        with lock:
            active += 1
            peak = max(active, peak)
        try:
            barrier.wait(timeout=5)
            return html()
        finally:
            with lock:
                active -= 1

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        report = smoke.run_smoke(SITE, concurrency=2, client=client)
    assert report.ok and peak == 2


def test_infinite_pagination_stops_at_url_limit_with_failure_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "MAX_URLS", 4)
    requested: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/sitemap.xml":
            return sitemap("/pages?n=1")
        number = int(request.url.params["n"])
        assert number <= 3, "the request limit was exceeded"
        return html(f"<a href='/pages?n={number + 1}'>next page</a>")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        report = smoke.run_smoke(SITE, client=client)
    assert not report.ok and report.summary["total"] == 4
    assert len(requested) == 4
    assert SITE + "/pages?n=4" not in requested
    assert len(report.failures) == 1
    failure = report.failures[0]
    assert failure.source == SITE + "/pages?n=3"
    assert failure.url == SITE + "/pages?n=4"
    assert "incompleta" in failure.reason


def test_real_landing_pages_and_their_shared_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seo, "PUBLIC_PAGES", (dict(pages.LANDING_PATHS),))
    routes = {"/sitemap.xml": httpx.Response(200, text=seo.sitemap_xml(SITE))}
    image_paths: set[str] = set()
    for locale, path in pages.LANDING_PATHS.items():
        routes[path] = html(pages.landing(locale=locale, base_url=SITE))
        image_path = "/static/" + seo.og_image_name("default", locale)
        image_paths.add(image_path)
        routes[image_path] = httpx.Response(200, headers={"content-type": "image/png"})
    site = Site(routes)
    with site.client() as client:
        report = smoke.run_smoke(SITE, only="images", client=client)
    assert report.ok
    assert {request.url.path for request in site.requests} == {
        "/sitemap.xml",
        *pages.LANDING_PATHS.values(),
        *image_paths,
    }
    assert all(count == 1 for count in site.counts().values())


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--site", "rigorscore.com"],
        ["--site", "https://rigorscore.com/path"],
        ["--site", SITE, "--concurrency", "0"],
        ["--site", SITE, "--concurrency", "5"],
        ["--site", SITE, "--timeout", "0"],
        ["--site", SITE, "--timeout", "nan"],
        ["--site", SITE, "--timeout", "inf"],
        ["--site", SITE, "--only", "other"],
    ],
)
def test_cli_rejects_invalid_arguments_before_opening_client(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    def refuse_client(*_: object, **__: object) -> None:
        raise AssertionError("invalid arguments must not open a client")

    monkeypatch.setattr(smoke, "_new_client", refuse_client)
    result = runner.invoke(app, ["audit", "smoke", *args])
    assert result.exit_code == 2, result.output


@pytest.mark.parametrize("status", [200, 404])
def test_cli_writes_only_requested_json_and_never_opens_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: int
) -> None:
    def refuse_database(*_: object, **__: object) -> None:
        raise AssertionError("the smoke command must not open a database")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'forbidden.db'}")
    monkeypatch.setattr(sqlite3, "connect", refuse_database)
    site = Site({"/sitemap.xml": sitemap("/"), "/": httpx.Response(status)})
    opened: list[httpx.Client] = []

    def new_client(concurrency: int, timeout: float) -> httpx.Client:
        assert concurrency == 2 and timeout == 7
        opened.append(site.client())
        return opened[-1]

    monkeypatch.setattr(smoke, "_new_client", new_client)
    arguments = ["audit", "smoke", "--site", SITE, "--concurrency", "2", "--timeout", "7"]
    result = runner.invoke(app, arguments)
    expected_exit = 0 if status == 200 else 1
    assert result.exit_code == expected_exit, result.output
    assert "total=2" in result.output
    assert "no-200=" in result.output
    assert not find_claims(result.output)
    if status != 200:
        assert "origen:" in result.output and SITE + "/sitemap.xml" in result.output
    assert list(tmp_path.iterdir()) == []
    output = tmp_path / "smoke.json"
    result = runner.invoke(app, [*arguments, "--json", str(output)])
    assert result.exit_code == expected_exit, result.output
    assert list(tmp_path.iterdir()) == [output]
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["non_200"] == (status != 200)
    assert bool(payload["failures"]) == (status != 200)
    assert opened and all(client.is_closed for client in opened)


def test_cli_help_and_external_output_pass_the_profit_claim_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    help_result = runner.invoke(app, ["audit", "smoke", "--help"])
    assert help_result.exit_code == 0 and not find_claims(help_result.output)
    site = Site(
        {
            "/sitemap.xml": sitemap("/"),
            "/": html("<a href='https://external.example/guide'>guide</a>"),
        }
    )
    monkeypatch.setattr(smoke, "_new_client", lambda *_: site.client())
    result = runner.invoke(app, ["audit", "smoke", "--site", SITE])
    assert result.exit_code == 0, result.output
    assert "Externo, no comprobado" in result.output
    assert "https://external.example/guide" in result.output
    assert "origen: " + SITE + "/" in result.output
    assert not find_claims(result.output)


def test_local_http_site_and_timeout_are_passed_to_requests() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.host == "127.0.0.1" and request.url.port == 8765
        assert request.headers["user-agent"] == "RigorSmoke/1.0"
        assert request.extensions["timeout"]["read"] == 1.5
        if request.url.path == "/sitemap.xml":
            return httpx.Response(
                200,
                text="<urlset><url><loc>http://127.0.0.1:8765/</loc></url></urlset>",
            )
        assert request.url.path == "/"
        return html()

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        report = smoke.run_smoke("http://127.0.0.1:8765", timeout=1.5, client=client)
    assert report.ok and len(seen) == 2
