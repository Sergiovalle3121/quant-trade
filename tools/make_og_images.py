"""Render the 1200x630 share images in ``static/`` with the site fonts.

- ``og-{es,en}.png``: the site card (landing, guides, method, legal pages).
- ``og-class-{A,B,C,D}-{es,en}.png``: a published verification page (``/v/...``),
  showing only the class, its fixed sentence and the fixed notice.
- ``og-sample-{es,en}.png``: the sample report, marked as synthetic data.
- ``og-for-{slug}-{es,en}.png``: each audience page, with its own title.
- ``og-pt.png`` and ``og-for-{slug}-pt.png``: the Portuguese site and audience cards.

Nothing on a card comes from a client file: every text is a fixed string the
pages already show. Run with Playwright and Chromium available:
python tools/make_og_images.py [output_dir]
"""

import html
import io
import sys
import tempfile
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

from quant_trade.audit.audiences import AUDIENCE_PAGES
from quant_trade.audit.pages import _UI, BADGE_NOTICE, SAMPLE_BANNER, class_text
from quant_trade.audit.seo import BRAND, OG_IMAGES, TAGLINE
from quant_trade.audit.theme import CLASS_COLOURS, STATIC_DIR, logo_mark, ring_svg

FONTS = STATIC_DIR / "fonts"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else STATIC_DIR

STYLE = """
@font-face{font-family:Inter;src:url('__INTER__') format('woff2');font-weight:100 900}
@font-face{font-family:Mono;src:url('__MONO__') format('woff2');font-weight:100 900}
*{margin:0;box-sizing:border-box}
body{width:1200px;height:630px;overflow:hidden;background:#000;color:#f4f4f6;
font-family:Inter,sans-serif;position:relative}
.glow{position:absolute;inset:-40% -10% auto;height:760px;
background:radial-gradient(50% 50% at 50% 0,rgba(255,255,255,.14),transparent 70%)}
.grid{position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.05) 1px,
transparent 1px),linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px);
background-size:60px 60px;mask-image:radial-gradient(70% 80% at 50% 30%,#000,transparent)}
.wrap{position:absolute;inset:72px 80px;display:flex;flex-direction:column}
.top{display:flex;align-items:center;justify-content:space-between}
.brand{display:flex;align-items:center;gap:16px;font-size:34px;font-weight:640;
letter-spacing:-.03em}
.brand svg{width:52px;height:52px}
.eyebrow{font:500 20px Mono,monospace;letter-spacing:.14em;text-transform:uppercase;
color:#8a8a92}
h1{margin-top:auto;font-size:76px;line-height:1.02;font-weight:660;letter-spacing:-.05em;
max-width:960px}
h1.sm{font-size:64px;line-height:1.06}
h1 span{color:#7c7c84}
.row{display:flex;gap:14px;margin-top:40px;font:500 20px Mono,monospace;letter-spacing:.04em}
.pill{display:flex;align-items:center;gap:10px;padding:9px 18px;border-radius:99px;
border:1px solid}
.pill::before{content:'';width:9px;height:9px;border-radius:50%;background:currentColor}
.m{color:#34c759;border-color:rgba(52,199,89,.4);background:rgba(52,199,89,.1)}
.d{color:#f5a524;border-color:rgba(245,165,36,.4);background:rgba(245,165,36,.1)}
.n{color:#9a9aa2;border-color:rgba(255,255,255,.2);background:rgba(255,255,255,.05)}
.classes{display:flex;gap:10px;font-size:30px;font-weight:640}
.classes b{width:58px;height:58px;display:grid;place-items:center;border-radius:16px;
border:1px solid rgba(255,255,255,.18);color:#9a9aa2}
.cls{margin-top:auto;display:flex;align-items:center;gap:56px}
.cls svg{width:250px;height:250px;flex:none}
.cls svg circle:first-child{stroke:rgba(255,255,255,.12)}
.cls svg text{font-family:Inter,sans-serif;letter-spacing:-.04em}
.cls h1{margin:0;font-size:84px}
.cls p{margin-top:18px;font-size:32px;line-height:1.3;color:#b4b4bc;max-width:720px;
letter-spacing:-.01em}
.note{margin-top:auto;font:500 19px Mono,monospace;color:#7c7c84;letter-spacing:.02em}
"""


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _page(body: str) -> str:
    style = STYLE.replace("__INTER__", (FONTS / "inter-var.woff2").as_uri()).replace(
        "__MONO__", (FONTS / "jetbrains-mono-var.woff2").as_uri()
    )
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><style>{style}</style></head>"
        f"<body><div class='glow'></div><div class='grid'></div><div class='wrap'>{body}"
        "</div></body></html>"
    )


def _brand(right: str) -> str:
    brand = f"<div class='brand'>{logo_mark(52)}<span>{BRAND}</span></div>"
    return f"<div class='top'>{brand}{right}</div>"


PILLS = (
    "<div class='row'><span class='pill m'>MEASURED</span><span class='pill d'>DECLARED</span>"
    "<span class='pill n'>NOT_MEASURED</span></div>"
)
CLASSES = "<div class='classes'><b>A</b><b>B</b><b>C</b><b>D</b></div>"


def site_card(locale: str) -> str:
    ui = _UI[locale]
    return _page(
        _brand(CLASSES) + f"<h1>{_e(ui['hero_a'])} <span>{_e(ui['hero_b'])}</span></h1>" + PILLS
    )


def class_card(overall: str, locale: str, *, eyebrow: str, note: str) -> str:
    head, _, rest = class_text(overall, locale).partition(": ")
    # The whole fixed sentence: class A keeps "not a prediction of future results".
    rest = rest[:1].upper() + rest[1:]
    colour = CLASS_COLOURS[overall]
    return _page(
        _brand(f"<span class='eyebrow'>{_e(eyebrow)}</span>")
        + "<div class='cls'>"
        + ring_svg(overall, css_class="r", letter=True)
        + f"<div><h1 style='color:{colour}'>{_e(head)}</h1><p>{_e(rest)}</p></div></div>"
        + f"<div class='note'>{_e(note)}</div>"
    )


def audience_card(title: str, locale: str) -> str:
    # The tagline up to "of backtests…": "Auditoría estadística independiente".
    eyebrow = TAGLINE[locale].split(" de ")[0].split(" of ")[0]
    return _page(
        _brand(f"<span class='eyebrow'>{_e(eyebrow)}</span>")
        + f"<h1 class='sm'>{_e(title)}</h1>"
        + PILLS
    )


def cards() -> dict[str, str]:
    out: dict[str, str] = {}
    for locale in ("es", "en"):
        out[f"og-{locale}.png"] = site_card(locale)
        eyebrow = _UI[locale]["v_eyebrow"]
        for overall in "ABCD":
            out[f"og-class-{overall}-{locale}.png"] = class_card(
                overall, locale, eyebrow=eyebrow, note=BADGE_NOTICE[locale]
            )
        sample = "Ejemplo" if locale == "es" else "Sample"
        out[f"og-sample-{locale}.png"] = class_card(
            "C", locale, eyebrow=sample, note=SAMPLE_BANNER[locale].split(":")[0]
        )
        for audience in AUDIENCE_PAGES:
            out[f"og-for-{audience.slug}-{locale}.png"] = audience_card(
                audience.text[locale].title, locale
            )
    # Portuguese: the site card and the audience cards (first sales' texts). Its class
    # and sample cards wait for a Portuguese class sentence and notice.
    out["og-pt.png"] = site_card("pt")
    for audience in AUDIENCE_PAGES:
        out[f"og-for-{audience.slug}-pt.png"] = audience_card(audience.text["pt"].title, "pt")
    return {name: out[name] for name in OG_IMAGES}


def _small_png(raw: bytes) -> bytes:
    """A 256-colour PNG: a fraction of the size, with no visible change on a dark card."""
    image = (
        Image.open(io.BytesIO(raw)).convert("RGB").quantize(colors=256, dither=Image.Dither.NONE)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def main() -> None:
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch(
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
        )
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        for name, markup in cards().items():
            # A file page, so the file:// fonts load (about:blank may not read them).
            source = Path(tmp) / "card.html"
            source.write_text(markup, encoding="utf-8")
            page.goto(source.as_uri())
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(150)
            (OUT / name).write_bytes(_small_png(page.screenshot()))
        browser.close()


if __name__ == "__main__":
    main()
