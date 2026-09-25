"""Render the 1200x630 share images (static/og-es.png, og-en.png) with the site fonts.

Run with Playwright and Chromium available: python tools/make_og_images.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from quant_trade.audit.pages import _UI
from quant_trade.audit.theme import STATIC_DIR, logo_mark

FONTS = STATIC_DIR / "fonts"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else STATIC_DIR

PAGE = """<!doctype html><html><head><meta charset='utf-8'><style>
@font-face{{font-family:Inter;src:url('{inter}') format('woff2');font-weight:100 900}}
@font-face{{font-family:Mono;src:url('{mono}') format('woff2');font-weight:100 900}}
*{{margin:0;box-sizing:border-box}}
body{{width:1200px;height:630px;overflow:hidden;background:#000;color:#f4f4f6;
font-family:Inter,sans-serif;position:relative}}
.glow{{position:absolute;inset:-40% -10% auto;height:760px;
background:radial-gradient(50% 50% at 50% 0,rgba(255,255,255,.14),transparent 70%)}}
.grid{{position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.05) 1px,
transparent 1px),linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px);
background-size:60px 60px;mask-image:radial-gradient(70% 80% at 50% 30%,#000,transparent)}}
.wrap{{position:absolute;inset:72px 80px;display:flex;flex-direction:column}}
.brand{{display:flex;align-items:center;gap:16px;font-size:34px;font-weight:640;
letter-spacing:-.03em}}
.brand svg{{width:52px;height:52px}}
h1{{margin-top:auto;font-size:76px;line-height:1.02;font-weight:660;letter-spacing:-.05em;
max-width:940px}}
h1 span{{color:#7c7c84}}
.row{{display:flex;gap:14px;margin-top:40px;font:500 20px Mono,monospace;letter-spacing:.04em}}
.pill{{display:flex;align-items:center;gap:10px;padding:9px 18px;border-radius:99px;
border:1px solid}}
.pill::before{{content:'';width:9px;height:9px;border-radius:50%;background:currentColor}}
.m{{color:#34c759;border-color:rgba(52,199,89,.4);background:rgba(52,199,89,.1)}}
.d{{color:#f5a524;border-color:rgba(245,165,36,.4);background:rgba(245,165,36,.1)}}
.n{{color:#9a9aa2;border-color:rgba(255,255,255,.2);background:rgba(255,255,255,.05)}}
.classes{{position:absolute;right:0;top:0;display:flex;gap:10px;font-size:30px;
font-weight:640}}
.classes b{{width:58px;height:58px;display:grid;place-items:center;border-radius:16px;
border:1px solid rgba(255,255,255,.18);color:#9a9aa2}}
</style></head><body><div class='glow'></div><div class='grid'></div><div class='wrap'>
<div class='brand'>{mark}<span>Rigor</span></div>
<div class='classes'><b>A</b><b>B</b><b>C</b><b>D</b></div>
<h1>{hero_a} <span>{hero_b}</span></h1>
<div class='row'><span class='pill m'>MEASURED</span><span class='pill d'>DECLARED</span>
<span class='pill n'>NOT_MEASURED</span></div></div></body></html>"""


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
        )
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        for locale in ("es", "en"):
            ui = _UI[locale]
            page.set_content(
                PAGE.format(
                    inter=(FONTS / "inter-var.woff2").as_uri(),
                    mono=(FONTS / "jetbrains-mono-var.woff2").as_uri(),
                    mark=logo_mark(52),
                    hero_a=ui["hero_a"],
                    hero_b=ui["hero_b"],
                )
            )
            page.wait_for_timeout(400)
            page.screenshot(path=str(OUT / f"og-{locale}.png"))
        browser.close()


if __name__ == "__main__":
    main()
