# ruff: noqa: E501  (long lines are CSS rules and data URIs)
"""The visual system every audit page shares: fonts, colours, layout, motion.

One stylesheet, inlined in every page so a report saved to disk keeps its
look; the self-hosted fonts and the small progressive-enhancement script are
served from ``/static`` (same origin, so the content security policy stays
strict and no visitor request reaches a third party). Without the fonts the
pages fall back to system fonts; without the script every page still works:
it only adds file-name previews on the upload fields, scroll reveals, the
"working" overlay while an audit runs and a copy button for the badge code.

Motion honours ``prefers-reduced-motion`` and printing always gets a light,
static page.
"""

from __future__ import annotations

import html
from pathlib import Path

from quant_trade.audit.seo import BRAND

STATIC_DIR = Path(__file__).with_name("static")

#: Every file ``/static/{name}`` may serve, with its media type. Nothing else
#: under the directory is reachable: the route looks names up here and never
#: joins a request path onto the filesystem.
STATIC_FILES: dict[str, str] = {
    "app.js": "text/javascript; charset=utf-8",
    "fonts/inter-var.woff2": "font/woff2",
    "fonts/jetbrains-mono-var.woff2": "font/woff2",
    # The link preview shown when a page is shared (tools/make_og_images.py).
    "og-es.png": "image/png",
    "og-en.png": "image/png",
}

#: Cache static files for a week; their names change when their content does.
STATIC_CACHE_CONTROL = "public, max-age=604800"

SCRIPT_SRC = "/static/app.js"
#: The brand mark as the tab icon, inline so it needs no request.
FAVICON = (
    "<link rel='icon' type='image/svg+xml' href=\"data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='9' fill='%23111113'/%3E%3Cpath d='M5 23c3.5 0 5-11 11-11"
    "s7.5 11 11 11' fill='none' stroke='%23f4f4f6' stroke-width='2.2' stroke-linecap='round'/%3E"
    "%3Cpath d='M20.5 7v18' stroke='%238a8a90' stroke-width='2' stroke-linecap='round'/%3E%3C/svg%3E\">"
)
SCRIPT_TAG = FAVICON + f"<script src='{SCRIPT_SRC}' defer></script>"

#: Class colours, shared by the report, the verification page and the badge.
CLASS_COLOURS: dict[str, str] = {"A": "#16a34a", "B": "#65a30d", "C": "#d97706", "D": "#dc2626"}
#: How much of the ring each class fills: a visual cue, not a score.
CLASS_RING: dict[str, int] = {"A": 92, "B": 72, "C": 46, "D": 22}


def static_file(name: str) -> tuple[bytes, str] | None:
    """``(content, media type)`` of an allowed static file, else ``None``."""
    media_type = STATIC_FILES.get(name)
    if media_type is None:
        return None
    return (STATIC_DIR / name).read_bytes(), media_type


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def logo_mark(size: int = 28) -> str:
    """The brand mark: a bell curve cut by a threshold line, drawn inline."""
    return (
        f"<svg class='mark' width='{size}' height='{size}' viewBox='0 0 32 32' aria-hidden='true'>"
        "<rect x='.5' y='.5' width='31' height='31' rx='9' fill='#111113' "
        "stroke='rgba(255,255,255,.16)'/>"
        "<path d='M5 23c3.5 0 5-11 11-11s7.5 11 11 11' fill='none' stroke='#f4f4f6' "
        "stroke-width='2.2' stroke-linecap='round'/>"
        "<path d='M20.5 7v18' stroke='#8a8a90' stroke-width='2' stroke-linecap='round'/>"
        "</svg>"
    )


def logo(home: str) -> str:
    return f"<a class='logo' href='{_e(home)}'>{logo_mark()}<span>{_e(BRAND)}</span></a>"


def class_ring(overall: str, *, size: str = "") -> str:
    """The class letter inside a ring that fills on load."""
    colour = CLASS_COLOURS.get(overall, "#64748b")
    fill = CLASS_RING.get(overall, 0)
    extra = f" ring-{size}" if size else ""
    return (
        f"<div class='ring{extra}' style='--c:{colour};--to:{fill}'>"
        f"<span class='cls' style='color:{colour}'>{_e(overall)}</span></div>"
    )


ICONS: dict[str, str] = {
    "check": "<path d='M5 12.5l4.2 4.2L19 7'/>",
    "shield": "<path d='M12 3l7 3v6c0 4.4-3 7.8-7 9-4-1.2-7-4.6-7-9V6z'/>",
    "hash": "<path d='M9 4L7 20M17 4l-2 16M4 9h16M3 15h16'/>",
    "globe": (
        "<circle cx='12' cy='12' r='9'/><path d='M3 12h18M12 3c2.5 2.8 3.8 5.8 3.8 9"
        "s-1.3 6.2-3.8 9c-2.5-2.8-3.8-5.8-3.8-9S9.5 5.8 12 3z'/>"
    ),
    "key": "<circle cx='8' cy='15' r='4'/><path d='M11 12l9-9M17 6l3 3M14 9l2 2'/>",
    "bell": "<path d='M4 19c3-5 4-14 8-14s5 9 8 14'/><path d='M4 19h16'/>",
    "layers": "<path d='M12 3l9 5-9 5-9-5z'/><path d='M3 13l9 5 9-5'/>",
    "percent": "<path d='M19 5L5 19'/><circle cx='7' cy='7' r='2.5'/><circle cx='17' cy='17' r='2.5'/>",
    "split": "<path d='M4 20V4M20 20V4M4 12h16'/><path d='M12 8v8' stroke-dasharray='2 2'/>",
    "database": (
        "<ellipse cx='12' cy='5' rx='8' ry='3'/><path d='M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5'/>"
        "<path d='M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3'/>"
    ),
    "target": "<circle cx='12' cy='12' r='9'/><circle cx='12' cy='12' r='5'/><circle cx='12' "
    "cy='12' r='1'/>",
    "upload": "<path d='M12 16V4M7 9l5-5 5 5'/><path d='M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3'/>",
    "file": "<path d='M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z'/><path d='M14 3v5h5'/>",
    "dice": (
        "<rect x='4' y='4' width='16' height='16' rx='3'/><circle cx='9' cy='9' r='1'/>"
        "<circle cx='15' cy='15' r='1'/><circle cx='15' cy='9' r='1'/><circle cx='9' cy='15' r='1'/>"
    ),
    "chat": "<path d='M4 19l1.4-4.2A8 8 0 1112 20a8 8 0 01-3.9-1z'/>",
    "arrow": "<path d='M5 12h14M13 6l6 6-6 6'/>",
    "card": "<rect x='3' y='5.5' width='18' height='13' rx='2.5'/><path d='M3 10h18M7 15h4'/>",
    "lock": "<rect x='5' y='11' width='14' height='10' rx='2'/><path d='M8 11V8a4 4 0 018 0v3'/>",
    "print": (
        "<path d='M7 9V3h10v6'/><rect x='3' y='9' width='18' height='8' rx='2'/>"
        "<path d='M7 14h10v7H7z'/>"
    ),
    "copy": "<rect x='8' y='8' width='12' height='12' rx='2'/><path d='M16 8V5a1 1 0 00-1-1H5"
    "a1 1 0 00-1 1v10a1 1 0 001 1h3'/>",
    "chart": "<path d='M4 20V4M4 20h16'/><path d='M7 15l4-5 3 3 5-7'/>",
    "eye": "<path d='M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z'/><circle cx='12' cy='12' "
    "r='3'/>",
}


def icon(name: str) -> str:
    return (
        "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.7' "
        f"stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>{ICONS[name]}</svg>"
    )


FONTS = """
@font-face{font-family:'Inter';font-style:normal;font-weight:100 900;font-display:swap;
src:url('/static/fonts/inter-var.woff2') format('woff2')}
@font-face{font-family:'JetBrains Mono';font-style:normal;font-weight:100 800;font-display:swap;
src:url('/static/fonts/jetbrains-mono-var.woff2') format('woff2')}
@property --p{syntax:'<number>';inherits:false;initial-value:0}
"""

BASE = """
:root{--ink:#000;--ink-2:#0b0b0d;--ink-3:#141416;
--sans:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
--serif:var(--sans);
--mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
--r-sm:10px;--r:14px;--r-lg:24px;--r-xl:30px;--ease:cubic-bezier(.22,.8,.2,1);
--bg:var(--ink);--surface:#0e0e10;--surface-2:#17171a;--surface-solid:#0e0e10;
--text:#f4f4f6;--text-2:#a3a3aa;--text-3:#707077;--head-2:#8a8a90;
--border:rgba(255,255,255,.085);--border-2:rgba(255,255,255,.16);--field:#0e0e10;
--btn-bg:#f4f4f6;--btn-fg:#000;--accent:#8fb0ff;
--shadow:0 40px 90px -40px rgba(0,0,0,.85);--ok:#34c759;--warn:#ffb340;--bad:#ff5a4f;
--info:#a9bcff;color-scheme:dark}
.paper,.light{--bg:#f4f4f6;--surface:#fff;--surface-2:#ececf0;--surface-solid:#fff;
--text:#111113;--text-2:#46464c;--text-3:#72727a;--head-2:#8a8a90;--border:rgba(0,0,0,.085);
--border-2:rgba(0,0,0,.16);--field:#fff;--btn-bg:#111113;--btn-fg:#fff;--accent:#1f5eff;
--shadow:0 30px 70px -38px rgba(0,0,0,.28);--ok:#1a7f37;--warn:#a85a00;--bad:#c42b21;
--info:#2f3fb0;color-scheme:light;background:var(--bg);color:var(--text)}
.dark{--bg:var(--ink);--surface:#0e0e10;--surface-2:#17171a;--surface-solid:#0e0e10;
--text:#f4f4f6;--text-2:#a3a3aa;--text-3:#707077;--border:rgba(255,255,255,.085);
--border-2:rgba(255,255,255,.16);--field:#0e0e10;--btn-bg:#f4f4f6;--btn-fg:#000;--accent:#8fb0ff;
--ok:#34c759;--warn:#ffb340;--bad:#ff5a4f;color-scheme:dark;background:var(--bg);color:var(--text)}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth;scroll-padding-top:80px}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);font-size:16px;
line-height:1.6;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;
text-rendering:optimizeLegibility;font-feature-settings:'cv11','ss01','ss03';overflow-x:hidden}
img,svg{max-width:100%;height:auto}
a{color:inherit;text-decoration-thickness:1px;text-underline-offset:3px;
text-decoration-color:color-mix(in srgb,currentColor 40%,transparent);transition:color .2s,text-decoration-color .2s}
a:hover{text-decoration-color:currentColor}
::selection{background:rgba(143,176,255,.35);color:#fff}
.paper ::selection,.light ::selection{background:rgba(31,94,255,.14);color:inherit}
:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:8px}
p{margin:0 0 1em}
h1,h2,h3{line-height:1.08;letter-spacing:-.03em;margin:0;font-weight:620}
code,pre{font-family:var(--mono)}
code{font-size:.82em;word-break:break-all;background:var(--surface-2);border:1px solid var(--border);
padding:1px 6px;border-radius:6px}
pre{white-space:pre-wrap;word-break:break-all;background:var(--surface-2);border:1px solid
var(--border);padding:14px 16px;border-radius:12px;font-size:.82rem;margin:0}
pre code{background:none;border:0;padding:0}
.skip{position:absolute;left:-999px;top:10px;background:#fff;color:#000;padding:8px 12px;
border-radius:8px;z-index:100}.skip:focus{left:10px}
.wrap{width:100%;max-width:1200px;margin:0 auto;padding:0 24px}
.wrap-mid{max-width:1000px}.wrap-narrow{max-width:800px}
.display{font-weight:640;letter-spacing:-.052em;line-height:.98}
.display em,.h2 em{font-style:normal;color:var(--head-2)}
.grad-text{background:linear-gradient(180deg,var(--text) 30%,var(--head-2));-webkit-background-clip:text;
background-clip:text;color:transparent}
.h2{font-weight:640;font-size:clamp(2.3rem,5vw,4.1rem);letter-spacing:-.046em;line-height:1.02}
.eyebrow{display:inline-flex;align-items:center;gap:10px;font:500 .72rem/1.4 var(--mono);
letter-spacing:.14em;text-transform:uppercase;color:var(--text-3)}
.pill{display:inline-flex;align-items:center;gap:10px;padding:6px 14px 6px 11px;border-radius:999px;
border:1px solid var(--border-2);background:rgba(255,255,255,.03);font-size:.8rem;
color:var(--text-2);backdrop-filter:blur(8px)}
.dot{width:6px;height:6px;border-radius:50%;background:var(--ok);flex:none;
box-shadow:0 0 0 3px color-mix(in srgb,var(--ok) 22%,transparent);animation:pulse 2.8s ease-in-out infinite}
.lead{font-size:clamp(1.08rem,1.5vw,1.24rem);color:var(--text-2);max-width:38em;line-height:1.55;
letter-spacing:-.012em}
.muted{color:var(--text-3);font-size:.9rem}
.mono{font-family:var(--mono)}
.section{padding:clamp(96px,12vw,168px) 0;position:relative}
.section-tight{padding:clamp(48px,6vw,80px) 0}
.section-head{max-width:820px;margin-bottom:clamp(44px,6vw,72px)}
.section-head .eyebrow{margin-bottom:22px}.section-head .lead{margin-top:22px}
.center{text-align:center;margin-left:auto;margin-right:auto}
.center .lead{margin-left:auto;margin-right:auto}
.divider{height:1px;background:var(--border);border:0;margin:0}
"""

NAV = """
.nav{position:sticky;top:0;z-index:50;background:rgba(0,0,0,.66);
border-bottom:1px solid rgba(255,255,255,.07);backdrop-filter:saturate(180%) blur(20px);
-webkit-backdrop-filter:saturate(180%) blur(20px);transition:background .35s}
.nav.scrolled,.nav-solid{background:rgba(0,0,0,.8)}
.nav-in{display:flex;align-items:center;gap:22px;height:60px}
.logo{display:inline-flex;align-items:center;gap:10px;text-decoration:none;font-weight:650;
font-size:1.05rem;letter-spacing:-.03em;color:var(--text)}
.nav .logo{color:#f4f4f6}
.logo .mark{width:26px;height:26px;transition:transform .6s var(--ease)}
.logo:hover .mark{transform:rotate(-6deg)}
.nav-links{display:flex;gap:0;margin-left:14px}
.nav-links a{text-decoration:none;color:#a3a3aa;font-size:.82rem;font-weight:450;padding:8px 12px;
border-radius:999px;transition:color .2s}
.nav-links a:hover{color:#fff}
.nav-end{margin-left:auto;display:flex;align-items:center;gap:10px}
.lang{font-size:.76rem;font-weight:500;color:#a3a3aa;text-decoration:none;padding:7px 10px;
border-radius:999px;transition:color .2s}
.lang:hover{color:#fff}
.nav .btn-sm{--h:32px;padding:0 15px;font-size:.8rem}
.menu{display:none;position:relative}
.menu>summary{list-style:none;cursor:pointer;width:40px;height:40px;border-radius:12px;display:grid;
place-items:center;transition:background .2s}
.menu>summary::-webkit-details-marker{display:none}
.menu>summary:hover{background:rgba(255,255,255,.08)}
.burger{display:grid;gap:5px;width:18px}
.burger i{display:block;height:1.5px;border-radius:2px;background:#f4f4f6;transition:transform .35s var(--ease),opacity .2s}
.menu[open] .burger i:nth-child(1){transform:translateY(6.5px) rotate(45deg)}
.menu[open] .burger i:nth-child(2){opacity:0}
.menu[open] .burger i:nth-child(3){transform:translateY(-6.5px) rotate(-45deg)}
.menu-panel{position:absolute;right:0;top:calc(100% + 10px);width:min(300px,calc(100vw - 32px));
display:grid;gap:2px;padding:10px;border-radius:20px;border:1px solid rgba(255,255,255,.12);
background:rgba(14,14,16,.96);box-shadow:0 30px 60px -20px rgba(0,0,0,.8);
backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);animation:drop .35s var(--ease)}
.menu-panel a{text-decoration:none;color:#e6e6ea;font-size:1rem;padding:12px 14px;border-radius:12px}
.menu-panel a:hover{background:rgba(255,255,255,.07)}
.menu-panel .btn{margin-top:8px;color:#000;background:#f4f4f6}
@media (max-width:920px){.nav-links{display:none}.menu{display:block}}
@media (max-width:520px){.nav-end>.lang{display:none}}
@media (max-width:520px){.nav-end>.btn{display:none}.nav-in{height:56px}}
"""

BUTTONS = """
.btn{--h:48px;position:relative;display:inline-flex;align-items:center;justify-content:center;
gap:8px;height:var(--h);padding:0 24px;border-radius:999px;font:560 .95rem/1 var(--sans);
letter-spacing:-.012em;text-decoration:none;border:0;cursor:pointer;color:var(--btn-fg);
background:var(--btn-bg);white-space:nowrap;
transition:transform .35s var(--ease),background .25s,color .25s,box-shadow .25s,opacity .25s}
.btn:hover{opacity:.88}
.btn:active{transform:scale(.97)}
.btn svg{width:17px;height:17px;transition:transform .35s var(--ease)}
.btn:hover .go{transform:translateX(3px)}
.go{display:inline-flex}
.btn-primary{background:var(--btn-bg);color:var(--btn-fg)}
.btn-ghost{background:transparent;color:var(--text);box-shadow:0 0 0 1px var(--border-2) inset}
.btn-ghost:hover{opacity:1;background:var(--surface-2)}
.btn-dark{background:#111113;color:#f4f4f6}
.btn-sm{--h:36px;padding:0 16px;font-size:.84rem}
.btn-lg{--h:54px;padding:0 30px;font-size:1rem}
.btn-block{width:100%}
.link-more{display:inline-flex;align-items:center;gap:6px;color:var(--accent);font-weight:500;
text-decoration:none;font-size:1rem;letter-spacing:-.01em}
.link-more svg{width:15px;height:15px;transition:transform .35s var(--ease)}
.link-more:hover{text-decoration:underline}
.link-more:hover svg{transform:translateX(3px)}
@media (max-width:620px){.hero-cta .btn{width:100%;white-space:normal;text-align:center}}
.btn[aria-busy=true]{pointer-events:none;opacity:.6}
"""

HERO = """
.hero{position:relative;overflow:hidden;padding:clamp(72px,11vw,148px) 0 0;isolation:isolate;
text-align:center}
.grid-bg{position:absolute;inset:0;z-index:-2;pointer-events:none;
background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),
linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);background-size:80px 80px;
-webkit-mask-image:radial-gradient(ellipse 70% 55% at 50% 0%,#000 10%,transparent 70%);
mask-image:radial-gradient(ellipse 70% 55% at 50% 0%,#000 10%,transparent 70%)}
.aurora{position:absolute;left:50%;top:-38vw;width:120vw;height:70vw;transform:translateX(-50%);
z-index:-1;pointer-events:none;border-radius:50%;
background:radial-gradient(closest-side,rgba(255,255,255,.1),rgba(140,165,255,.05) 45%,transparent)}
.aurora span{display:none}
.hero h1{font-size:clamp(2.1rem,8.4vw,5.9rem);margin:28px auto 26px;max-width:13em}
.hero h1 .l{display:block}
.hero .lead{margin:0 auto}
.hero-cta{display:flex;flex-wrap:wrap;gap:14px 28px;margin-top:40px;align-items:center}
.hero .hero-cta{justify-content:center}
.trust{display:flex;flex-wrap:wrap;justify-content:center;gap:10px 28px;margin:44px 0 0;padding:0;
list-style:none;color:var(--text-3);font-size:.84rem}
.trust li{display:flex;align-items:center;gap:8px}
.trust svg{width:15px;height:15px;color:var(--text-2);flex:none}
.rise{opacity:0;transform:translateY(22px);filter:blur(6px);animation:rise 1.1s var(--ease) forwards;
animation-delay:calc(var(--i,0) * 90ms + 60ms)}
.page-hero{position:relative;overflow:hidden;isolation:isolate;padding:clamp(56px,8vw,104px) 0
clamp(48px,6vw,80px);border-bottom:1px solid var(--border)}
.page-hero .aurora{top:-34vw;opacity:1}
.page-hero::after{content:'';position:absolute;left:0;right:0;bottom:0;height:1px;z-index:-1;
background:linear-gradient(90deg,transparent,rgba(255,255,255,.55) 50%,transparent);
box-shadow:0 0 28px 2px rgba(160,180,255,.22)}
.page-hero h1{font-weight:640;font-size:clamp(2.6rem,5.6vw,4.6rem);letter-spacing:-.048em;
line-height:1;margin:16px 0 18px;max-width:14em}
.page-hero .lead{margin:0}
.crumbs{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;font-size:.84rem;
color:var(--text-3)}
.crumbs a{text-decoration:none;color:var(--text-2)}.crumbs a:hover{color:var(--text)}
"""

MOCK = """
.stage{position:relative;margin:clamp(64px,9vw,112px) auto 0;max-width:1120px;perspective:2000px;
padding:0 0 clamp(72px,9vw,120px)}
.stage::before{content:'';position:absolute;left:8%;right:8%;top:18%;bottom:6%;z-index:-1;
border-radius:50%;filter:blur(80px);background:radial-gradient(closest-side,rgba(150,170,255,.22),
rgba(255,255,255,.05) 60%,transparent)}
.mock{position:relative;border-radius:26px;border:1px solid rgba(255,255,255,.14);
background:linear-gradient(180deg,#111114,#0a0a0c);text-align:left;overflow:hidden;
box-shadow:0 1px 0 rgba(255,255,255,.08) inset,0 90px 160px -70px rgba(0,0,0,1),
0 40px 80px -40px rgba(0,0,0,.8);transform-origin:50% 0}
@supports (animation-timeline:view()){
.stage .mock{animation:tilt linear both;animation-timeline:view();animation-range:entry 0% cover 42%}}
.mock-top{display:flex;align-items:center;gap:12px;padding:14px 18px;
border-bottom:1px solid rgba(255,255,255,.07)}
.mock-top i{width:10px;height:10px;border-radius:50%;background:rgba(255,255,255,.13);display:block}
.mock-dots{display:flex;gap:7px}
.mock-url{margin:0 auto;font:500 .72rem var(--mono);color:#86868c;background:rgba(255,255,255,.05);
padding:5px 14px;border-radius:999px;transform:translateX(-22px)}
.mock-body{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr)}
.mock-col{padding:clamp(22px,3vw,34px)}
.mock-col+.mock-col{border-left:1px solid rgba(255,255,255,.07)}
.mock-head{display:flex;gap:20px;align-items:center}
.mock-k{font:500 .66rem var(--mono);letter-spacing:.14em;text-transform:uppercase;color:#76767d}
.mock-t{font-size:.98rem;font-weight:500;color:#e6e6ea;line-height:1.4;margin-top:6px;
letter-spacing:-.01em}
.spark{display:block;width:100%;height:auto;margin:14px 0 0}
.spark-line{fill:none;stroke:#f4f4f6;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;
stroke-dasharray:1;stroke-dashoffset:1;animation:draw 2.6s var(--ease) .8s forwards}
.spark-area{fill:url(#spa);opacity:0;animation:fade 1.4s ease 2s forwards}
.spark-grid{stroke:rgba(255,255,255,.06);stroke-width:1}
.spark-split{stroke:rgba(255,255,255,.35);stroke-width:1;stroke-dasharray:3 4}
.spark-oos{fill:rgba(255,255,255,.035)}
.spark-lbl{font:500 8px var(--mono);fill:#76767d;letter-spacing:.08em;text-transform:uppercase}
.mock-dims{list-style:none;margin:22px 0 0;padding:0;display:grid}
.mock-dims li{display:flex;justify-content:space-between;align-items:center;gap:12px;
padding:10px 0;border-top:1px solid rgba(255,255,255,.06);font-size:.85rem;color:#c8c8ce;
opacity:0;animation:rise .8s var(--ease) forwards;animation-delay:calc(var(--i) * 100ms + 1.1s)}
.mock-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin-top:22px;
background:rgba(255,255,255,.07);border-radius:16px;overflow:hidden;border:1px solid rgba(255,255,255,.07)}
.mock-kpis div{background:#0d0d10;padding:14px 16px}
.mock-kpis strong{display:block;font-size:1.35rem;font-weight:600;letter-spacing:-.035em;color:#f4f4f6;
font-variant-numeric:tabular-nums}
.mock-kpis span{display:block;font-size:.72rem;color:#86868c;margin-top:2px}
.mock-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:18px}
.mock-cap{margin-top:18px;font-size:.74rem;color:var(--text-3);text-align:center}
@media (max-width:860px){.mock-body{grid-template-columns:minmax(0,1fr)}
.mock-col+.mock-col{border-left:0;border-top:1px solid rgba(255,255,255,.07)}}
@media (max-width:560px){.mock-url{transform:none}.mock-kpis strong{font-size:1.1rem}}
.ring{--p:0;position:relative;flex:none;width:86px;height:86px;border-radius:50%;display:grid;
place-items:center;background:conic-gradient(var(--c) calc(var(--p) * 1%),rgba(128,128,136,.2) 0);
animation:ring 2s var(--ease) .4s forwards}
.ring::before{content:'';position:absolute;inset:5px;border-radius:50%;background:var(--surface-solid)}
.ring .cls{position:relative;font-family:var(--sans);font-size:2.5rem;line-height:1;
font-weight:600;letter-spacing:-.04em;background:none;padding:0;margin:0}
.ring-lg{width:136px;height:136px}.ring-lg::before{inset:7px}.ring-lg .cls{font-size:4rem}
.ring-xl{width:172px;height:172px}.ring-xl::before{inset:8px}.ring-xl .cls{font-size:5.2rem}
.mock .ring::before{background:#0f0f12}
"""

SECTIONS = """
.specs{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:1px solid var(--border);
border-bottom:1px solid var(--border)}
.specs div{padding:clamp(28px,4vw,44px) clamp(16px,2.4vw,32px);text-align:center}
.specs div+div{border-left:1px solid var(--border)}
.specs b{display:block;font-size:clamp(2.8rem,5.4vw,4.6rem);font-weight:600;letter-spacing:-.055em;
line-height:1;font-variant-numeric:tabular-nums}
.specs span{display:block;margin-top:12px;color:var(--text-2);font-size:.9rem;letter-spacing:-.005em}
@media (max-width:760px){.specs{grid-template-columns:1fr 1fr}.specs div:nth-child(3){border-left:0}
.specs div:nth-child(-n+2){border-bottom:1px solid var(--border)}}
.platforms{padding:clamp(40px,5vw,64px) 0 0;text-align:center}
.platforms p{font:500 .7rem var(--mono);letter-spacing:.14em;text-transform:uppercase;
color:var(--text-3);margin:0 0 22px}
.platforms ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;justify-content:center;
gap:14px 40px}
.platforms li{font-weight:600;font-size:1.1rem;letter-spacing:-.03em;color:var(--text-3);
transition:color .3s}
.platforms li:hover{color:var(--text)}
.statement{font-size:clamp(1.6rem,3.2vw,2.6rem);font-weight:560;letter-spacing:-.034em;
line-height:1.22;max-width:1000px;margin:0 0 clamp(56px,7vw,96px);color:var(--text)}
@media (max-width:620px){.statement{font-size:1.28rem;line-height:1.35;letter-spacing:-.02em}}
@supports (animation-timeline:view()){
.js .statement{color:transparent;background:linear-gradient(180deg,var(--text) 50%,
color-mix(in srgb,var(--text) 22%,transparent) 50%) 0 100%/100% 200% no-repeat;
-webkit-background-clip:text;background-clip:text;animation:lit linear both;
animation-timeline:view();animation-range:entry 30% cover 55%}}
.trio{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:clamp(28px,4vw,56px)}
@media (max-width:860px){.trio{grid-template-columns:minmax(0,1fr)}}
.trio>div{border-top:1px solid var(--border-2);padding-top:28px}
.trio .n{font:500 .78rem var(--mono);color:var(--text-3);letter-spacing:.08em}
.trio h3{font-size:clamp(1.4rem,2.2vw,1.8rem);font-weight:620;letter-spacing:-.035em;margin:18px 0 12px}
.trio p{color:var(--text-2);margin:0;font-size:1rem;line-height:1.6}
.cards{display:grid;gap:16px;grid-template-columns:repeat(3,minmax(0,1fr))}
.cards-2{grid-template-columns:repeat(2,minmax(0,1fr))}
.cards-4{grid-template-columns:repeat(4,minmax(0,1fr))}
@media (max-width:980px){.cards,.cards-4{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:640px){.cards,.cards-2,.cards-4{grid-template-columns:minmax(0,1fr)}}
.card{position:relative;border:1px solid var(--border);border-radius:var(--r-lg);
background:var(--surface);padding:clamp(26px,3vw,36px);overflow:hidden;isolation:isolate;
transition:border-color .4s,transform .6s var(--ease),box-shadow .4s}
.card:hover{border-color:var(--border-2);transform:translateY(-4px)}
.paper .card,.light .card{border-color:transparent;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.paper .card:hover,.light .card:hover{box-shadow:var(--shadow)}
.spot::before{content:'';position:absolute;inset:0;border-radius:inherit;z-index:-1;
pointer-events:none;opacity:0;transition:opacity .5s;
background:radial-gradient(520px circle at var(--mx,50%) var(--my,0%),rgba(255,255,255,.07),
transparent 45%)}
.light .spot::before{background:radial-gradient(520px circle at var(--mx,50%) var(--my,0%),
rgba(31,94,255,.06),transparent 45%)}
.spot:hover::before{opacity:1}
.card h3{font-size:1.2rem;font-weight:620;letter-spacing:-.025em;margin:28px 0 10px}
.card p{margin:0;color:var(--text-2);font-size:.96rem;line-height:1.6}
.icon{width:44px;height:44px;border-radius:12px;display:grid;place-items:center;
color:var(--text);background:var(--surface-2);border:1px solid var(--border)}
.icon svg{width:22px;height:22px}
.num{font:500 .76rem var(--mono);color:var(--text-3);letter-spacing:.06em}
.big-num{font-size:clamp(3.4rem,6vw,4.8rem);font-weight:600;letter-spacing:-.05em;line-height:.9;
display:block}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;
border:1px solid var(--border);border-radius:var(--r-lg);overflow:hidden}
.stats div{padding:30px 26px;border-right:1px solid var(--border)}
.stats div:last-child{border-right:0}
.stats b{display:block;font-weight:600;font-size:clamp(2.4rem,4vw,3.2rem);line-height:1;
letter-spacing:-.05em}
.stats span{display:block;margin-top:10px;color:var(--text-2);font-size:.9rem}
@media (max-width:760px){.stats{grid-template-columns:1fr 1fr}.stats div:nth-child(2){border-right:0}
.stats div:nth-child(-n+2){border-bottom:1px solid var(--border)}}
.split{display:grid;grid-template-columns:minmax(0,.95fr) minmax(0,1.05fr);gap:clamp(40px,7vw,104px);
align-items:start}
@media (max-width:900px){.split{grid-template-columns:minmax(0,1fr)}}
.sticky{position:sticky;top:110px}
@media (max-width:900px){.sticky{position:static}}
.tags{display:grid;border-top:1px solid var(--border-2)}
.tag-row{display:grid;grid-template-columns:170px 1fr;gap:24px;align-items:center;padding:30px 0;
border-bottom:1px solid var(--border)}
.tag-row p{margin:0;color:var(--text);font-size:1.12rem;letter-spacing:-.015em;line-height:1.5}
@media (max-width:560px){.tag-row{grid-template-columns:minmax(0,1fr);gap:12px}}
.steps{counter-reset:s;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:24px;
list-style:none;padding:0;margin:0;position:relative}
.steps::before{content:'';position:absolute;left:0;right:0;top:22px;height:1px;background:var(--border-2)}
.steps li{position:relative;padding:0 8px 0 0;color:var(--text-2);font-size:1rem;line-height:1.55}
.steps li::before{counter-increment:s;content:counter(s,decimal-leading-zero);display:grid;
place-items:center;width:44px;height:44px;border-radius:50%;margin-bottom:26px;
font:500 .8rem var(--mono);color:var(--btn-fg);background:var(--btn-bg);
box-shadow:0 0 0 10px var(--bg);position:relative}
@media (max-width:900px){.steps{grid-template-columns:1fr 1fr;gap:40px 24px}.steps::before{display:none}}
@media (max-width:560px){.steps{grid-template-columns:minmax(0,1fr)}}
.list-steps{counter-reset:s;list-style:none;padding:0;margin:0;display:grid;gap:12px;
grid-template-columns:minmax(0,1fr)}
.list-steps li{overflow-wrap:anywhere}
.list-steps li{position:relative;padding:16px 18px 16px 62px;border:1px solid var(--border);
border-radius:var(--r);background:var(--surface);color:var(--text-2)}
.list-steps li::before{counter-increment:s;content:counter(s);position:absolute;left:16px;top:14px;
width:30px;height:30px;border-radius:50%;display:grid;place-items:center;
font:600 .8rem var(--mono);color:var(--btn-fg);background:var(--btn-bg)}
.checks{list-style:none;padding:0;margin:0;display:grid;gap:12px}
.checks li{display:flex;gap:12px;align-items:flex-start;color:var(--text-2);font-size:.96rem}
.checks li svg{width:18px;height:18px;flex:none;margin-top:3px;color:var(--text)}
.prices{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;max-width:1000px}
.prices-one{grid-template-columns:minmax(0,1fr);max-width:580px}
@media (max-width:760px){.prices{grid-template-columns:minmax(0,1fr)}}
.price{position:relative;border:1px solid var(--border);border-radius:var(--r-xl);
background:var(--surface);padding:clamp(28px,3.4vw,44px);display:flex;flex-direction:column}
.light .price{border-color:transparent;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.price.featured{--surface:#0e0e10;--surface-2:#17171a;--text:#f4f4f6;--text-2:#a3a3aa;
--text-3:#707077;--border:rgba(255,255,255,.1);--border-2:rgba(255,255,255,.18);--btn-bg:#f4f4f6;
--btn-fg:#000;--accent:#8fb0ff;background:#0e0e10;color:var(--text);color-scheme:dark;
box-shadow:0 60px 110px -60px rgba(0,0,0,.7)}
.dark .price.featured{--surface:#f4f4f6;--surface-2:#e6e6ea;--text:#111113;--text-2:#46464c;
--text-3:#72727a;--border:rgba(0,0,0,.09);--border-2:rgba(0,0,0,.16);--btn-bg:#111113;
--btn-fg:#fff;--accent:#1f5eff;--ok:#1a7f37;background:#f4f4f6;color-scheme:light;
box-shadow:0 60px 120px -60px rgba(255,255,255,.18)}
.price-name{font-weight:560;color:var(--text-2);font-size:.95rem}
.price-amount{font-size:clamp(3rem,5.4vw,4.4rem);font-weight:600;line-height:1;margin:16px 0 8px;
letter-spacing:-.055em}
.price-amount small{font-size:1rem;font-weight:450;color:var(--text-3);margin-left:8px;letter-spacing:-.01em}
.price .checks{margin:26px 0 30px;flex:1;align-content:start}
.price-pack{margin:6px 0 0;padding:12px 14px;border-radius:14px;background:var(--surface-2);
color:var(--text);font-size:.92rem}
.ribbon{position:absolute;top:24px;right:24px;font:500 .66rem var(--mono);letter-spacing:.1em;
text-transform:uppercase;padding:5px 10px;border-radius:999px;color:var(--btn-fg);background:var(--btn-bg)}
.pay-ways{margin:28px 0 0;max-width:1000px}
.refund-note{margin-top:16px}
.faq{max-width:900px}
.faq details{border-bottom:1px solid var(--border)}
.faq details:first-child{border-top:1px solid var(--border)}
.faq summary{list-style:none;cursor:pointer;padding:26px 56px 26px 0;font-weight:560;
font-size:1.14rem;position:relative;letter-spacing:-.02em;transition:color .2s}
.faq summary::-webkit-details-marker{display:none}
.faq summary:hover{color:var(--text-2)}
.faq summary::after{content:'';position:absolute;right:10px;top:50%;width:14px;height:14px;
margin-top:-7px;transition:transform .4s var(--ease);
background:linear-gradient(currentColor,currentColor) center/14px 1.5px no-repeat,
linear-gradient(currentColor,currentColor) center/1.5px 14px no-repeat}
.faq details[open] summary::after{transform:rotate(45deg)}
.faq details p{margin:0 0 28px;color:var(--text-2);max-width:62em;animation:fade .5s ease}
.cta-band{position:relative;isolation:isolate;padding:clamp(24px,4vw,48px) 0}
.cta-band .h2{font-size:clamp(2.6rem,6.4vw,5.6rem);letter-spacing:-.055em;line-height:1}
"""

FORMS = """
form{margin:0}
label,.label{display:block;font-weight:560;font-size:.88rem;margin:0 0 8px;color:var(--text);
letter-spacing:-.005em}
.field{margin:0 0 18px}
.help{color:var(--text-3);font-size:.83rem;margin-top:8px;line-height:1.5}
.help a{color:var(--text-2)}
input[type=text],input[type=number],input[type=email],input[type=date],input[type=url],
input[type=password],select,textarea{width:100%;
height:48px;padding:0 15px;border-radius:12px;border:1px solid var(--border-2);
background:var(--field);color:var(--text);font:inherit;font-size:.95rem;
transition:border-color .2s,box-shadow .2s,background .2s;-webkit-appearance:none;appearance:none}
textarea{height:auto;min-height:96px;padding:13px 15px;resize:vertical}
select{padding-right:42px;background-repeat:no-repeat;background-position:right 15px center;
background-size:14px;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%238a8a90' stroke-width='2.4' stroke-linecap='round'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")}
select option{background:#0e0e10;color:#f4f4f6}
.paper select option,.light select option{background:#fff;color:#111113}
input:hover,select:hover,textarea:hover{border-color:color-mix(in srgb,var(--text) 35%,transparent)}
input:focus,select:focus,textarea:focus{outline:0;border-color:var(--accent);
box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 22%,transparent)}
input::placeholder,textarea::placeholder{color:var(--text-3)}
input[type=date]::-webkit-calendar-picker-indicator{filter:invert(.7)}
.paper input[type=date]::-webkit-calendar-picker-indicator{filter:none}
.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}
@media (max-width:620px){.form-grid{grid-template-columns:minmax(0,1fr)}}
.check{display:flex;gap:13px;align-items:flex-start;font-weight:450;font-size:.9rem;
color:var(--text-2);line-height:1.55;cursor:pointer}
.check input{-webkit-appearance:none;appearance:none;width:22px;height:22px;flex:none;margin:1px 0 0;
border-radius:7px;border:1px solid var(--border-2);background:var(--field);display:grid;
place-items:center;cursor:pointer;transition:background .2s,border-color .2s}
.check input:checked{background:var(--btn-bg);border-color:transparent}
.check input:checked::after{content:'';width:10px;height:5px;border:2px solid var(--btn-fg);
border-top:0;border-right:0;transform:translateY(-1px) rotate(-45deg)}
.drop{position:relative;display:flex;align-items:center;gap:16px;padding:18px 20px;
border-radius:16px;border:1px dashed var(--border-2);background:var(--field);
transition:border-color .25s,background .25s,transform .35s var(--ease),box-shadow .25s}
.drop:hover,.drop.over{border-color:color-mix(in srgb,var(--text) 55%,transparent);
background:var(--surface-2)}
.drop.over{transform:scale(1.01);box-shadow:0 0 0 6px color-mix(in srgb,var(--text) 8%,transparent)}
.drop.has{border-style:solid;border-color:color-mix(in srgb,var(--ok) 60%,transparent);
background:color-mix(in srgb,var(--ok) 7%,var(--field))}
.drop .icon{width:42px;height:42px;flex:none}
.drop-txt{min-width:0;flex:1}
.drop-title{font-weight:560;font-size:.94rem;letter-spacing:-.01em}
.drop-sub{color:var(--text-3);font-size:.82rem;margin-top:2px}
.drop-file{font:500 .8rem var(--mono);color:var(--ok);margin-top:4px;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.drop-file:empty{display:none}
.drop input[type=file]{font-size:.84rem;color:var(--text-2);max-width:100%;margin-top:8px}
.js .drop input[type=file]{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;
cursor:pointer}
.drop-main{flex-direction:column;text-align:center;padding:44px 24px;gap:12px}
.drop-main .icon{width:56px;height:56px;border-radius:16px}
.drop-main .icon svg{width:26px;height:26px}
.drop-main .drop-title{font-size:1.1rem}
.drop-main.has .icon{color:var(--ok);background:color-mix(in srgb,var(--ok) 14%,transparent);
border-color:color-mix(in srgb,var(--ok) 40%,transparent);display:grid;place-items:center}
.drop-main.has .icon svg{display:none}
.drop-main.has .icon::after{content:'';width:20px;height:10px;border:2.5px solid currentColor;
border-top:0;border-right:0;transform:translateY(-3px) rotate(-45deg)}
.drop-main.has .formats{display:none}
.drop-main .drop-file{display:inline-block;max-width:100%;margin-top:4px;padding:6px 14px;
border-radius:99px;font-size:.86rem;background:color-mix(in srgb,var(--ok) 12%,transparent)}
.drop-main .drop-file:empty{display:none}
.formats{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin-top:6px}
.formats span{font:500 .7rem var(--mono);padding:3px 8px;border-radius:6px;color:var(--text-2);
border:1px solid var(--border)}
details.adv{border:1px solid var(--border);border-radius:16px;margin:6px 0 20px}
details.adv>summary{list-style:none;cursor:pointer;padding:16px 18px;display:flex;
align-items:center;justify-content:space-between;gap:12px;font-weight:560;font-size:.92rem}
details.adv>summary::-webkit-details-marker{display:none}
details.adv>summary small{font-weight:450;color:var(--text-3);font-size:.82rem}
details.adv>summary svg{width:16px;height:16px;transition:transform .35s var(--ease);flex:none}
details.adv[open]>summary svg{transform:rotate(180deg)}
.adv-body{padding:4px 18px 4px}
.upload{display:grid;grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr);
gap:clamp(36px,6vw,88px);align-items:start}
@media (max-width:960px){.upload{grid-template-columns:minmax(0,1fr)}}
.panel{position:relative;border:1px solid var(--border-2);border-radius:var(--r-xl);
padding:clamp(24px,3.4vw,40px);background:var(--surface);
box-shadow:0 1px 0 rgba(255,255,255,.06) inset,var(--shadow)}
.panel-note{display:flex;gap:10px;align-items:center;font-size:.86rem;color:var(--text-2);
margin:0 0 22px}
.panel-note svg{width:16px;height:16px;color:var(--ok);flex:none}
.submit-row{margin-top:24px}
.inline-form{display:flex;flex-wrap:wrap;gap:10px}
.inline-form input{flex:1 1 220px}
.busy{position:fixed;inset:0;z-index:90;display:none;place-items:center;padding:24px;
background:rgba(0,0,0,.86);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}
.busy.on{display:grid;animation:fade .35s ease}
.busy-card{width:100%;max-width:420px;text-align:center;color:#f4f4f6}
.busy-card h2{font-weight:620;letter-spacing:-.04em;font-size:2.1rem;margin:0 0 6px}
.loader{width:64px;height:64px;margin:0 auto 28px;border-radius:50%;
background:conic-gradient(from 0deg,transparent 0 25%,#f4f4f6);
-webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 3px),#000 calc(100% - 2px));
mask:radial-gradient(farthest-side,transparent calc(100% - 3px),#000 calc(100% - 2px));
animation:spin 1s linear infinite}
.busy ol{list-style:none;padding:0;margin:28px 0 0;display:grid;gap:12px;text-align:left}
.busy li{display:flex;gap:12px;align-items:center;color:#a3a3aa;opacity:.25;font-size:.95rem;
animation:on .6s var(--ease) forwards;animation-delay:calc(var(--i) * 1.3s + .3s)}
.busy li::before{content:'';width:6px;height:6px;border-radius:50%;background:#f4f4f6;flex:none}
"""

ALERTS = """
.flash,.error,.notice,.banner,.warning{border-radius:14px;padding:13px 16px;margin:14px 0;
font-size:.92rem;border:1px solid;line-height:1.5}
.flash{color:var(--ok);background:color-mix(in srgb,var(--ok) 9%,transparent);
border-color:color-mix(in srgb,var(--ok) 32%,transparent)}
.error{color:var(--bad);background:color-mix(in srgb,var(--bad) 8%,transparent);
border-color:color-mix(in srgb,var(--bad) 32%,transparent)}
.notice{color:var(--info);background:color-mix(in srgb,var(--info) 9%,transparent);
border-color:color-mix(in srgb,var(--info) 30%,transparent);font-weight:560}
.banner{color:var(--warn);background:color-mix(in srgb,var(--warn) 9%,transparent);
border-color:color-mix(in srgb,var(--warn) 32%,transparent);font-weight:600;letter-spacing:.01em}
.disclaimer{border:1px solid var(--border);border-radius:16px;padding:18px 20px;
background:var(--surface-2);color:var(--text-2);font-size:.86rem;line-height:1.6;margin:0}
.disclaimer strong{color:var(--text)}
"""

FOOTER = """
.foot{--bg:#f4f4f6;--text:#111113;--text-2:#46464c;--text-3:#72727a;--border:rgba(0,0,0,.09);
--border-2:rgba(0,0,0,.16);--surface-2:#ececf0;--field:#fff;--btn-bg:#111113;--btn-fg:#fff;
--accent:#1f5eff;background:var(--bg);color:var(--text-2);border-top:1px solid var(--border);
padding:clamp(56px,7vw,88px) 0 40px;color-scheme:light;font-size:.86rem}
.foot-grid{display:grid;grid-template-columns:1.6fr 1fr 1fr;gap:40px;margin-bottom:44px}
@media (max-width:760px){.foot-grid{grid-template-columns:1fr 1fr}.foot-grid>div:first-child{
grid-column:1/-1}}
.foot h4{font:500 .7rem var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--text-3);
margin:0 0 16px}
.foot ul{list-style:none;margin:0;padding:0;display:grid;gap:10px;font-size:.88rem}
.foot a{text-decoration:none;color:var(--text-2)}.foot a:hover{color:var(--text)}
.foot .tagline{margin:14px 0 0;max-width:32em;font-size:.88rem}
.foot .legal{margin:22px 0 0;font-size:.82rem}
.foot .disclaimer{background:transparent;padding:18px 0 0;border:0;border-top:1px solid var(--border);
border-radius:0;font-size:.8rem;color:var(--text-3)}
.foot-base{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;margin-top:28px;
padding-top:18px;border-top:1px solid var(--border);font-size:.78rem;color:var(--text-3)}
.news{margin:36px auto 0;max-width:460px}
.news .inline-form input{height:46px}
.news .label{color:var(--text-2);font-weight:450}
"""

REPORT = """
.report-hero{position:relative;overflow:hidden;isolation:isolate;padding:40px 0 64px}
.report-hero .aurora{top:-44vw}
.toolbar{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;
margin-bottom:34px}
.toolbar-end{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.print-btn{white-space:nowrap;display:inline-flex;align-items:center;gap:8px;height:34px;padding:0 15px;
border-radius:999px;border:0;background:#f4f4f6;color:#000;font:560 .8rem var(--sans);cursor:pointer;
transition:opacity .2s}
.print-btn:hover{opacity:.86}
.ladder{list-style:none;margin:22px 0 0;padding:0;display:grid;gap:10px}
.rung{display:grid;grid-template-columns:44px 1fr auto;gap:18px;align-items:center;padding:16px 20px;border-radius:16px;background:#fff;border:1px solid rgba(0,0,0,.08);color:#52525b}
.rung p{margin:0;font-size:.95rem;line-height:1.5}
.rung-cls{width:44px;height:44px;display:grid;place-items:center;border-radius:12px;font-weight:660;font-size:1.2rem;color:var(--c);border:1px solid color-mix(in srgb,var(--c) 35%,transparent);background:color-mix(in srgb,var(--c) 8%,#fff)}
.rung.you{border-color:var(--c);color:#0a0a0b;box-shadow:0 0 0 3px color-mix(in srgb,var(--c) 14%,transparent),0 10px 30px -18px rgba(0,0,0,.35)}
.rung.you .rung-cls{background:var(--c);color:#fff;border-color:var(--c)}
.rung-you{font:600 .7rem var(--mono);letter-spacing:.08em;text-transform:uppercase;white-space:nowrap;color:var(--c);padding:5px 10px;border-radius:999px;background:color-mix(in srgb,var(--c) 10%,#fff);border:1px solid color-mix(in srgb,var(--c) 35%,transparent)}
@media (max-width:620px){.rung{grid-template-columns:40px 1fr;gap:14px;padding:14px 16px;align-items:start}.rung-cls{width:40px;height:40px}.rung-you{grid-column:2;justify-self:start}}
@media print{.ladder{display:block;break-inside:avoid}.rung-cls,.rung-you{border:1px solid currentColor}.rung{margin:0 0 8px;break-inside:avoid;box-shadow:none}.rung{display:flex;align-items:center}.rung-cls{display:block;flex:none;width:34px;height:34px;line-height:32px;text-align:center;margin-right:16px}.rung p{flex:1;margin-right:14px}.rung-you{flex:none}}
a.print-btn{text-decoration:none}
.report-hero .verdict+p{margin-top:28px}
.print-btn svg{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:2.2}
@media (max-width:620px){.meta-line .meta-x{display:none}.meta-line span{font-size:.66rem}}
.lang-switch{font-size:.8rem;font-weight:500;text-decoration:none;color:#a3a3aa;padding:8px 12px;
border-radius:999px}
.lang-switch:hover{color:#fff}
.report-hero h1{font-weight:640;font-size:clamp(2.8rem,6vw,4.8rem);letter-spacing:-.05em;
line-height:1;margin:16px 0 18px}
.meta-line{display:flex;flex-wrap:wrap;gap:8px;margin:0}
.meta-line span{font:500 .72rem var(--mono);color:var(--text-2);padding:5px 10px;border-radius:8px;
background:rgba(255,255,255,.04);border:1px solid var(--border)}
.verdict{display:flex;gap:36px;align-items:center;margin:40px 0 0;padding:clamp(24px,3.4vw,40px);
border-radius:var(--r-xl);border:1px solid var(--border-2);
background:linear-gradient(180deg,#131316,#0c0c0e);
box-shadow:0 1px 0 rgba(255,255,255,.07) inset,var(--shadow)}
.verdict .ring::before{background:#101013}
.verdict-k{font:500 .68rem var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--text-3);
margin-bottom:10px}
.verdict-text{font-size:clamp(.98rem,1.3vw,1.08rem);line-height:1.65;color:#a3a3aa;margin:0;
letter-spacing:-.005em}
.verdict-lead{display:block;font-size:clamp(1.3rem,2.3vw,1.75rem);line-height:1.22;font-weight:600;
letter-spacing:-.03em;color:#f4f4f6;margin:0 0 14px}
.report-toc{position:sticky;top:60px;z-index:40;background:rgba(244,244,246,.95);
border-bottom:1px solid var(--border);backdrop-filter:saturate(180%) blur(18px);
-webkit-backdrop-filter:saturate(180%) blur(18px)}
.report-toc ol{list-style:none;margin:0;padding:10px 0;display:flex;gap:4px;overflow-x:auto;
scrollbar-width:none;-webkit-mask-image:linear-gradient(90deg,#000 92%,transparent);
mask-image:linear-gradient(90deg,#000 92%,transparent)}
.report-toc ol::-webkit-scrollbar{display:none}
.report-toc a{display:block;white-space:nowrap;padding:7px 13px;border-radius:999px;font-size:.8rem;
font-weight:500;color:#6e6e76;text-decoration:none;transition:color .2s,background .25s}
.report-toc a:hover{color:#111113}
.report-toc a.on{background:#111113;color:#f4f4f6}
.report-main .rsec,.report-main .detail,#unlock{scroll-margin-top:130px}
.paper td{font-variant-numeric:tabular-nums}
.recon{display:grid;gap:10px;margin:18px 0 0}
.recon-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:24px;
padding:18px 22px;background:#fff;border:1px solid var(--border);border-radius:18px}
.recon-k{font-weight:600;letter-spacing:-.01em}
.recon-v{display:flex;align-items:center;gap:18px}
.recon-v span{display:grid;gap:2px;text-align:right;min-width:92px}
.recon-v small{white-space:nowrap;font:500 .62rem var(--mono);letter-spacing:.12em;text-transform:uppercase;
color:var(--text-3)}
.recon-v b{font-size:1.35rem;font-weight:600;letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.recon-v i{font-style:normal;font-size:1.2rem;color:var(--text-3)}
.recon-row.bad{border-color:rgba(220,38,38,.35);box-shadow:0 0 0 3px rgba(220,38,38,.06)}
.recon-row.bad .recon-v i{color:#dc2626}
.recon-foot{margin:14px 0 0;font-size:.92rem;color:var(--text-2)}
.recon-foot.ok::before{content:'';display:inline-block;width:7px;height:7px;border-radius:50%;
background:#16a34a;margin-right:9px;vertical-align:2px}
@media (max-width:620px){.recon-row{grid-template-columns:minmax(0,1fr) auto;gap:12px 16px;padding:16px}
.recon-v{grid-column:1/-1;grid-row:2;justify-content:flex-start}
.recon-v span{text-align:left;min-width:0}}
@media (max-width:620px){.verdict{flex-direction:column;align-items:flex-start;gap:22px}}
.report-main{padding:clamp(48px,7vw,88px) 0 clamp(64px,9vw,112px)}
.rsec{margin:0 0 clamp(48px,6vw,72px)}
.rsec>h2,.detail>h2{font-size:clamp(1.5rem,2.4vw,1.9rem);font-weight:640;letter-spacing:-.04em;
margin:0 0 22px}
.detail{margin:0 0 clamp(40px,5vw,60px)}
.rsec h3,.detail h3{font-size:1.04rem;margin:24px 0 10px;font-weight:600;letter-spacing:-.02em}
.paper table{width:100%;border-collapse:separate;border-spacing:0;font-size:.88rem;
margin:.4em 0 1.2em;border:1px solid var(--border);border-radius:16px;overflow:hidden;
font-variant-numeric:tabular-nums;background:#fff}
table{border-collapse:collapse}
th,td{padding:12px 15px;text-align:left;vertical-align:top;border-bottom:1px solid var(--border)}
.paper tr:last-child>td{border-bottom:0}
th{background:#fafafb;font:500 .68rem var(--mono);text-transform:uppercase;letter-spacing:.1em;
color:var(--text-3)}
.paper tr:hover>td{background:#fafafb}
.paper table.metrics{table-layout:fixed}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:18px 0 8px}
.fact{background:#fff;border:1px solid var(--border);border-radius:18px;padding:20px 22px}
.fact b{display:block;font-size:2.2rem;font-size:clamp(1.9rem,3.2vw,2.5rem);font-weight:640;letter-spacing:-.05em;
line-height:1;font-variant-numeric:tabular-nums}
.fact p{margin:10px 0 0;color:var(--text-2);font-size:.92rem}
.paper table.timing{table-layout:fixed}
.paper table.stress{table-layout:fixed}
.stress .c-n{width:17%}.stress .c-b{width:190px}
.stress .val{text-align:right;padding-right:28px;white-space:nowrap}
.stress td.val{font-weight:600}.stress td.delta{font-weight:400;color:var(--text-3)}
.stress td.neg{color:#b91c1c}
.stress tr.base>td{background:var(--surface-2);font-weight:600}
@media (max-width:759px){.paper table.stress{table-layout:auto}.stress .val{padding-right:16px}
.stress td:first-child{min-width:190px}}
.timing .c-k{width:24%}.timing .c-n{width:14%}
.timing .val{text-align:right}
.timing td.val{font-weight:600;white-space:nowrap}
.tbar b{display:inline-block;min-width:92px;font-weight:600}
.tbar-track{display:inline-block;vertical-align:middle;width:calc(100% - 110px);height:6px;
margin-right:10px;border-radius:99px;background:var(--surface-2);overflow:hidden;direction:rtl}
.tbar-track span{display:block;height:100%;width:var(--w);border-radius:99px;background:var(--text)}
.tbar.neg .tbar-track span{background:#dc2626}.tbar.neg b{color:#b91c1c}
@media (max-width:759px){.paper table.timing{table-layout:auto}.tbar-track{display:none}}
.live .val{text-align:right;white-space:nowrap}.live th{white-space:normal}.live td:first-child{font-weight:500}
.live-verdict{margin:18px 0;padding:16px 20px;border-radius:16px;background:#fff;border:1px solid var(--border);border-left:4px solid #9a9aa2;line-height:1.6}
.lv-PASS{border-left-color:#16a34a}.lv-WEAK{border-left-color:#d97706}.lv-FAIL{border-left-color:#dc2626}
.live-verdict .badge{margin-right:6px}
@media (max-width:900px){.paper table.live,.live thead,.live tbody,.live tr,.live td{display:block}.paper table.live{overflow:visible;border:0;background:none;box-shadow:none}.live thead{display:none}.live tr{background:#fff;border:1px solid var(--border);border-radius:14px;padding:12px 14px;margin:0 0 8px}.live td{border:0!important;padding:3px 0!important;text-align:left!important;display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 12px;white-space:normal}.live td strong{white-space:normal}.live td:first-child{min-width:0;font-weight:600;padding-bottom:6px!important}.live td[data-l]::before{content:attr(data-l);color:var(--text-3);font-size:.8rem}.live td.empty{display:none}}
.pair .val{text-align:right}.pair td:first-child{font-weight:500;width:55%}
@media (max-width:620px){.pair tr{display:block;padding:10px 0}.pair td{display:block;width:auto!important;text-align:left!important;border:0!important;padding:2px 14px!important}.pair tr+tr{border-top:1px solid var(--border)}}
.metrics .c-k{width:30%}.metrics .c-v{width:15%}.metrics .c-e{width:170px}
.metrics td:first-child{font-weight:500}
.metrics .val{text-align:right;padding-right:28px}
.metrics td.val{color:var(--text);font-size:.95rem;font-weight:600;letter-spacing:-.01em;white-space:nowrap}
@media (max-width:759px){.paper table.metrics{table-layout:auto}.metrics .val{padding-right:18px}.metrics td:first-child{min-width:150px}}
.paper figure.chart svg{background:#fff;border-radius:18px;border:1px solid var(--border)}
@media (max-width:620px){
.paper figure.chart{overflow-x:auto;-webkit-overflow-scrolling:touch}
.paper figure.chart svg{min-width:560px}
.paper figure.chart svg text{font-size:14px}
.paper figure.chart figcaption{position:sticky;left:0;max-width:calc(100vw - 48px)}}
.badge{display:inline-flex;align-items:center;gap:6px;padding:3px 10px 3px 8px;border-radius:999px;
font:500 .66rem/1.5 var(--mono);letter-spacing:.03em;border:1px solid transparent;
white-space:nowrap;vertical-align:middle}
.badge::before{content:'';width:5px;height:5px;border-radius:50%;background:currentColor;flex:none}
.MEASURED,.PASS{color:var(--ok);background:color-mix(in srgb,var(--ok) 10%,transparent);
border-color:color-mix(in srgb,var(--ok) 30%,transparent)}
.DECLARED,.WEAK,.WARN{color:var(--warn);background:color-mix(in srgb,var(--warn) 10%,transparent);
border-color:color-mix(in srgb,var(--warn) 32%,transparent)}
.FAIL,.ERROR{color:var(--bad);background:color-mix(in srgb,var(--bad) 9%,transparent);
border-color:color-mix(in srgb,var(--bad) 30%,transparent)}
.NOT_MEASURED,.NOT_APPLICABLE,.INFO{color:var(--text-3);background:rgba(128,128,136,.1);
border-color:rgba(128,128,136,.3)}
.status{display:inline-flex;padding:3px 10px;border-radius:999px;font-size:.78rem;font-weight:560;
background:var(--surface-2);border:1px solid var(--border)}
.meaning{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:0}
@media (max-width:760px){.meaning{grid-template-columns:minmax(0,1fr)}}
.meaning .item{position:relative;border:1px solid transparent;border-radius:20px;
padding:22px 24px 20px;background:#fff;overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,.04);
transition:box-shadow .35s,transform .45s var(--ease)}
.meaning .item:hover{box-shadow:var(--shadow);transform:translateY(-2px)}
.meaning .item h3{font-size:1.02rem;margin:0 0 10px;display:flex;flex-wrap:wrap;
justify-content:space-between;gap:8px;align-items:center;font-weight:600;letter-spacing:-.02em}
.meaning .item p{margin:0;color:var(--text-2);font-size:.93rem}
.meaning .item::before{content:'';position:absolute;left:0;top:18px;bottom:18px;width:3px;
border-radius:0 3px 3px 0;background:var(--sc,#c7c7cc)}
.meaning .s-PASS{--sc:#34c759}.meaning .s-WEAK{--sc:#ff9f0a}.meaning .s-FAIL{--sc:#ff453a}
.paper .kpi{border-color:transparent;box-shadow:0 1px 2px rgba(0,0,0,.04);border-radius:20px;padding:20px 22px}
.paper .kpi b{font-family:var(--sans);font-weight:600;letter-spacing:-.045em}
.flag-list{list-style:none;padding:0;margin:0;display:grid;gap:8px}
.flag-list li{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:13px 16px;
border:1px solid transparent;border-radius:14px;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.watermark{position:fixed;top:42%;left:4%;right:4%;text-align:center;font-size:clamp(2.4rem,7vw,5.4rem);
font-weight:700;letter-spacing:.02em;color:rgba(196,43,33,.08);transform:rotate(-22deg);
pointer-events:none;z-index:9}
.lockbox{position:relative;overflow:hidden;isolation:isolate;border-radius:var(--r-xl);
padding:clamp(28px,4.4vw,52px);margin:0 0 48px;color:#f4f4f6;
background:radial-gradient(90% 120% at 50% -20%,rgba(255,255,255,.12),transparent 60%),#0c0c0e;
--text:#f4f4f6;--text-2:#a3a3aa;--text-3:#707077;--border:rgba(255,255,255,.12);
--border-2:rgba(255,255,255,.2);--field:rgba(255,255,255,.05);--surface-2:#17171a;--btn-bg:#f4f4f6;
--btn-fg:#000;--accent:#8fb0ff;--ok:#34c759;color-scheme:dark}
.lockbox>p:first-child{font-size:clamp(1.3rem,2.3vw,1.8rem);font-weight:600;letter-spacing:-.03em;max-width:30em;
line-height:1.2;margin:0 0 28px;color:#fff}
.lockbox ul{list-style:none;padding:0;margin:0 0 28px;display:grid;
grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 24px}
@media (max-width:620px){.lockbox ul{grid-template-columns:minmax(0,1fr)}}
.lockbox li{display:flex;gap:10px;align-items:center;color:#c8c8ce;font-size:.93rem}
.lockbox li::before{content:'';width:14px;height:14px;flex:none;opacity:.7;
background:no-repeat center/contain url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f4f4f6' stroke-width='2' stroke-linecap='round'%3E%3Crect x='5' y='11' width='14' height='10' rx='2'/%3E%3Cpath d='M8 11V8a4 4 0 018 0v3'/%3E%3C/svg%3E")}
.paybox{margin:12px 0 0;padding:18px;border-radius:18px;border:1px solid var(--border);
background:rgba(255,255,255,.04)}
.paybox label{color:#ececf0}
.paybox .inline-form{margin-top:8px}
.paybox a{color:#fff;font-weight:560}
.paybox.buy{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:18px;
padding:22px 24px;background:rgba(255,255,255,.07);border-color:var(--border-2)}
.buy-price b{display:block;font-size:2.4rem;font-weight:650;letter-spacing:-.05em;line-height:1;
color:#fff;font-variant-numeric:tabular-nums}
.buy-price span{display:block;margin-top:8px;color:var(--text-2);font-size:.9rem}
.buy-price span::first-letter{text-transform:uppercase}
.paybox.buy a.btn{color:var(--btn-fg);gap:10px}
.paybox.buy .btn{gap:10px}.paybox.buy .btn svg{width:18px;height:18px;flex:none}
.pay-secure{display:flex;gap:8px;align-items:flex-start;margin:14px 0 0;font-size:.85rem}
.pay-secure svg{width:15px;height:15px;flex:none;margin-top:3px}
.paybox.pay-alt{padding:14px 18px}
.pay-alt a{display:inline-flex;align-items:center;gap:10px;color:var(--text-2);font-weight:500;text-decoration:none}
.pay-alt a:hover{color:#fff}
.pay-alt svg{width:18px;height:18px;flex:none}
.pay-alt span{text-decoration:underline;text-underline-offset:3px;text-decoration-color:rgba(255,255,255,.3)}
@media (max-width:620px){.paybox.buy{padding:20px}.paybox.buy .btn{width:100%;padding:0 14px;font-size:.93rem;white-space:normal;text-align:center}.paybox.buy a.btn svg{display:none}.paybox.buy .inline-form{width:100%}.paybox.buy .inline-form .btn{flex:1 1 100%}.paybox.buy .btn-ghost{font-size:.85rem;padding:0 10px;white-space:nowrap}.pay-alt a{align-items:flex-start}.pay-alt svg{margin-top:3px}}
.publish{display:flex;flex-wrap:wrap;gap:18px;align-items:center;justify-content:space-between;
padding:26px 28px;border-radius:var(--r-lg);background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.04);
margin:0 0 40px}
.publish p{margin:0;max-width:40em}
.report-foot{display:grid;gap:14px}
"""

VERIFY = """
.v-hero{display:grid;grid-template-columns:auto minmax(0,1fr);gap:clamp(24px,4vw,56px);
align-items:center}
@media (max-width:620px){.v-hero{grid-template-columns:minmax(0,1fr)}}
.v-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin-top:30px;
background:var(--border);border:1px solid var(--border);border-radius:16px;overflow:hidden}
@media (max-width:760px){.v-facts{grid-template-columns:minmax(0,1fr)}}
.v-facts div{padding:16px 18px;background:#0b0b0d}
.v-facts b{display:block;font:500 .66rem var(--mono);letter-spacing:.14em;text-transform:uppercase;
color:var(--text-3);margin-bottom:6px}
.v-facts span{font:500 .86rem var(--mono);color:var(--text);word-break:break-all}
.badge-preview{padding:32px;border-radius:var(--r-lg);background:#fff;text-align:center;
box-shadow:0 1px 2px rgba(0,0,0,.04)}
.copy-row{display:flex;justify-content:flex-end;margin-top:10px}
.guide-list{list-style:none;padding:0;margin:0;display:grid;gap:14px;
grid-template-columns:repeat(2,minmax(0,1fr))}
@media (max-width:700px){.guide-list{grid-template-columns:minmax(0,1fr)}}
.guide-list a{display:flex;flex-direction:column;gap:6px;height:100%;padding:24px 26px;
border-radius:var(--r-lg);background:#fff;text-decoration:none;box-shadow:0 1px 2px rgba(0,0,0,.04);
transition:box-shadow .35s,transform .45s var(--ease)}
.guide-list a:hover{box-shadow:var(--shadow);transform:translateY(-3px)}
.guide-list b{font-size:1.08rem;font-weight:600;letter-spacing:-.025em;display:flex;
justify-content:space-between;gap:10px}
.guide-list b svg{width:18px;height:18px;color:var(--text-3);transition:transform .35s var(--ease),color .3s}
.guide-list a:hover b svg{transform:translateX(4px);color:var(--text)}
.guide-list span{color:var(--text-2);font-size:.93rem}
.prose{max-width:760px}
.prose h2{font-size:1.4rem;font-weight:620;letter-spacing:-.03em;margin:2.2em 0 .7em}
.prose h2:first-child{margin-top:0}
.prose p,.prose li{color:var(--text-2)}
.prose ul{padding-left:1.2em}.prose li{margin:.35em 0}
.prose h2{scroll-margin-top:96px}
.doc{display:grid;grid-template-columns:minmax(0,760px) minmax(200px,248px);gap:clamp(40px,7vw,96px);
justify-content:space-between;align-items:start}
.toc{position:sticky;top:96px}
.toc-in{border-left:1px solid var(--border);padding:2px 0 2px 22px}
.toc b{display:block;font-family:var(--mono);font-size:.68rem;font-weight:500;letter-spacing:.16em;
text-transform:uppercase;color:var(--text-3);margin:0 0 14px}
.toc ol{list-style:none;margin:0;padding:0;display:grid;gap:2px}
.toc ol a{display:block;position:relative;padding:6px 0;font-size:.86rem;line-height:1.35;
color:var(--text-3);text-decoration:none;transition:color .2s}
.toc ol a::before{content:'';position:absolute;left:-23px;top:6px;bottom:6px;width:1px;
background:var(--text);transform:scaleY(0);transition:transform .35s var(--ease)}
.toc ol a:hover,.toc ol a.on{color:var(--text)}
.toc ol a.on::before{transform:scaleY(1)}
.toc-cta{margin-top:24px}
.doc-foot{margin-top:40px}
@media (max-width:980px){.doc{grid-template-columns:minmax(0,1fr)}.toc{display:none}}
.page-main{padding:clamp(52px,7vw,96px) 0 clamp(72px,10vw,128px)}
.back-row{display:flex;flex-wrap:wrap;gap:12px;margin-top:44px}
"""

MOTION = """
[data-reveal]{transition:opacity 1.1s var(--ease),transform 1.1s var(--ease),filter 1.1s var(--ease);
transition-delay:calc(var(--i,0) * 90ms)}
.js [data-reveal]:not(.in){opacity:0;transform:translateY(32px);filter:blur(6px)}
@keyframes rise{to{opacity:1;transform:none;filter:none}}
@keyframes drop{from{opacity:0;transform:translateY(-8px)}}
@keyframes fade{from{opacity:0}to{opacity:1}}
@keyframes on{to{opacity:1;color:#f4f4f6}}
@keyframes draw{to{stroke-dashoffset:0}}
@keyframes ring{to{--p:var(--to)}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes tilt{from{transform:rotateX(16deg) scale(.92);opacity:.5}to{transform:none;opacity:1}}
@keyframes lit{to{background-position:0 0}}
@keyframes pulse{0%,100%{box-shadow:0 0 0 3px color-mix(in srgb,var(--ok) 22%,transparent)}
50%{box-shadow:0 0 0 7px color-mix(in srgb,var(--ok) 0%,transparent)}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;
animation-delay:0s!important;animation-iteration-count:1!important;transition-duration:.01ms!important;
scroll-behavior:auto!important}.js [data-reveal]:not(.in){opacity:1;transform:none;filter:none}
.stage .mock{animation:none!important}.js .statement{animation:none!important;color:var(--text);
background:none}}
"""

PRINT = """
@media print{
.recon-row{padding:12px 18px;gap:16px;break-inside:avoid;box-shadow:none!important}
.recon-v span{min-width:0}
.metrics .val{padding-right:14px}.tbar-track{width:calc(100% - 100px)}.fact{break-inside:avoid}.fact b{font-size:24pt!important}.metrics .c-v{width:17%}
.recon-v i{margin:0 16px}.recon-row .badge{margin-left:18px}
:root,.hero,.page-hero,.report-hero,.lockbox,.verdict{--bg:#fff;--surface:#fff;--surface-2:#f4f4f6;
--surface-solid:#fff;--text:#000;--text-2:#333;--text-3:#555;--border:#ddd;--border-2:#ccc;
--ok:#1a7f37;--warn:#a85a00;--bad:#c42b21;color-scheme:light}
body,.report-hero,.verdict,.lockbox,.paper{background:#fff!important;color:#000!important;
box-shadow:none!important}
.nav,.toc,.no-print,.paybox,.print-btn,.publish,.aurora,.grid-bg,.foot,.busy,.lang-switch{
display:none!important}
.report-hero{padding:0}.report-main{padding:12px 0}
.wrap{max-width:none;padding:0}body{font-size:10.5pt}
.verdict-text,.verdict-lead,.report-hero h1,.lockbox>p:first-child{color:#000!important}
.verdict .ring::before{background:#fff}
[data-reveal],.rise{opacity:1!important;transform:none!important;filter:none!important;animation:none!important}
.ring{--p:var(--to);animation:none}
.meaning .item,.kpi,.flag-list li{border:1px solid #ddd!important}
.paper table{display:table}
h2{break-after:avoid;page-break-after:avoid}
table,.meaning .item,.verdict{break-inside:avoid;page-break-inside:avoid}
.badge,.verdict,.ring,.meaning .item::before{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.watermark{position:fixed}
}
@media (max-width:759px){.paper table{display:block;overflow-x:auto}}
"""

#: The full stylesheet, inlined in every page.
STYLE = FONTS + BASE + NAV + BUTTONS + HERO + MOCK + SECTIONS + FORMS + ALERTS + FOOTER
STYLE += REPORT + VERIFY + MOTION + PRINT


def aurora() -> str:
    """A soft light from above the fold (decorative)."""
    return "<div class='aurora' aria-hidden='true'></div>"


def grid_bg() -> str:
    return "<div class='grid-bg' aria-hidden='true'></div>"


__all__ = [
    "CLASS_COLOURS",
    "SCRIPT_SRC",
    "SCRIPT_TAG",
    "STATIC_CACHE_CONTROL",
    "STATIC_FILES",
    "STYLE",
    "aurora",
    "class_ring",
    "grid_bg",
    "icon",
    "logo",
    "logo_mark",
    "static_file",
]
