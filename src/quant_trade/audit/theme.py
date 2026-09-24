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
    "fonts/instrument-serif.woff2": "font/woff2",
    "fonts/instrument-serif-italic.woff2": "font/woff2",
    "fonts/jetbrains-mono-var.woff2": "font/woff2",
}

#: Cache static files for a week; their names change when their content does.
STATIC_CACHE_CONTROL = "public, max-age=604800"

SCRIPT_SRC = "/static/app.js"
#: The brand mark as the tab icon, inline so it needs no request.
FAVICON = (
    "<link rel='icon' type='image/svg+xml' href=\"data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect x='1' y='1' width='30' height='30' rx='9' fill='%230d121c' stroke='%239aa8ff'"
    " stroke-width='1.5'/%3E%3Cpath d='M5 23c3.5 0 5-11 11-11s7.5 11 11 11' fill='none'"
    " stroke='%23f4f6fb' stroke-width='2' stroke-linecap='round'/%3E%3Cpath d='M20.5 7v18'"
    " stroke='%236ee7d8' stroke-width='2' stroke-linecap='round'/%3E%3C/svg%3E\">"
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
        "<defs><linearGradient id='mk' x1='0' y1='0' x2='1' y2='1'>"
        "<stop offset='0' stop-color='#9aa8ff'/><stop offset='1' stop-color='#6ee7d8'/>"
        "</linearGradient></defs>"
        "<rect x='1' y='1' width='30' height='30' rx='9' fill='#0d121c' stroke='url(#mk)' "
        "stroke-width='1.5'/>"
        "<path d='M5 23c3.5 0 5-11 11-11s7.5 11 11 11' fill='none' stroke='#f4f6fb' "
        "stroke-width='2' stroke-linecap='round'/>"
        "<path d='M20.5 7v18' stroke='url(#mk)' stroke-width='2' stroke-linecap='round'/>"
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
    "coins": (
        "<ellipse cx='12' cy='6' rx='7' ry='3'/><path d='M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6'/>"
        "<path d='M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6'/>"
    ),
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
    "arrow": "<path d='M5 12h14M13 6l6 6-6 6'/>",
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
@font-face{font-family:'Instrument Serif';font-style:normal;font-weight:400;font-display:swap;
src:url('/static/fonts/instrument-serif.woff2') format('woff2')}
@font-face{font-family:'Instrument Serif';font-style:italic;font-weight:400;font-display:swap;
src:url('/static/fonts/instrument-serif-italic.woff2') format('woff2')}
@font-face{font-family:'JetBrains Mono';font-style:normal;font-weight:100 800;font-display:swap;
src:url('/static/fonts/jetbrains-mono-var.woff2') format('woff2')}
@property --p{syntax:'<number>';inherits:false;initial-value:0}
"""

BASE = """
:root{--ink:#05070b;--ink-2:#0a0e15;--ink-3:#111722;
--grad:linear-gradient(120deg,#9aa8ff 0%,#7dd3fc 45%,#6ee7d8 100%);
--accent:#9aa8ff;--accent-2:#6ee7d8;
--sans:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
--serif:'Instrument Serif',ui-serif,Georgia,'Times New Roman',serif;
--mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
--r-sm:10px;--r:14px;--r-lg:22px;--r-xl:30px;--ease:cubic-bezier(.2,.7,.2,1);
--bg:var(--ink);--surface:rgba(255,255,255,.035);--surface-2:rgba(255,255,255,.06);
--surface-solid:#0c1119;--text:#f4f6fb;--text-2:#b6bfcc;--text-3:#7f8898;
--border:rgba(255,255,255,.09);--border-2:rgba(255,255,255,.17);--field:rgba(255,255,255,.04);
--shadow:0 40px 90px -40px rgba(0,0,0,.8);--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;
--info:#a5b4fc;color-scheme:dark}
.paper{--bg:#fff;--surface:#fff;--surface-2:#f4f5f8;--surface-solid:#fff;--text:#0a0d14;
--text-2:#3f4755;--text-3:#687182;--border:#e5e7ed;--border-2:#cfd4de;--field:#fff;
--shadow:0 30px 70px -40px rgba(15,23,42,.28);--accent:#4f5dff;--ok:#15803d;--warn:#b45309;
--bad:#b91c1c;--info:#3730a3;color-scheme:light;background:var(--bg);color:var(--text)}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth;scroll-padding-top:90px}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);font-size:16px;
line-height:1.6;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;
text-rendering:optimizeLegibility;font-feature-settings:'cv11','ss01';overflow-x:hidden}
img,svg{max-width:100%;height:auto}
a{color:inherit;text-decoration-thickness:1px;text-underline-offset:3px;
text-decoration-color:rgba(127,136,152,.6);transition:color .2s,text-decoration-color .2s}
a:hover{text-decoration-color:currentColor}
::selection{background:rgba(154,168,255,.35);color:#fff}
.paper ::selection{background:rgba(79,93,255,.16);color:inherit}
:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:8px}
p{margin:0 0 1em}
h1,h2,h3{line-height:1.1;letter-spacing:-.022em;margin:0;font-weight:650}
code,pre{font-family:var(--mono)}
code{font-size:.82em;word-break:break-all;background:var(--surface-2);border:1px solid var(--border);
padding:1px 6px;border-radius:6px}
pre{white-space:pre-wrap;word-break:break-all;background:var(--surface-2);border:1px solid
var(--border);padding:14px 16px;border-radius:12px;font-size:.82rem;margin:0}
pre code{background:none;border:0;padding:0}
.skip{position:absolute;left:-999px;top:10px;background:#fff;color:#000;padding:8px 12px;
border-radius:8px;z-index:100}.skip:focus{left:10px}
.wrap{width:100%;max-width:1180px;margin:0 auto;padding:0 24px}
.wrap-mid{max-width:980px}.wrap-narrow{max-width:800px}
.display{font-family:var(--serif);font-weight:400;letter-spacing:-.018em;line-height:1}
.display em,.h2 em,.grad-text{font-style:italic;background:var(--grad);-webkit-background-clip:text;
background-clip:text;color:transparent;padding-right:.08em}
.h2{font-family:var(--serif);font-weight:400;font-size:clamp(2.2rem,4.4vw,3.6rem);
letter-spacing:-.015em;line-height:1.04}
.eyebrow{display:inline-flex;align-items:center;gap:10px;font-size:.74rem;font-weight:600;
letter-spacing:.14em;text-transform:uppercase;color:var(--text-2)}
.pill{display:inline-flex;align-items:center;gap:10px;padding:7px 14px 7px 10px;border-radius:999px;
border:1px solid var(--border-2);background:rgba(255,255,255,.04);font-size:.82rem;
color:var(--text-2);backdrop-filter:blur(8px)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--accent-2);flex:none;
box-shadow:0 0 0 4px rgba(110,231,216,.16);animation:pulse 2.6s ease-in-out infinite}
.lead{font-size:1.14rem;color:var(--text-2);max-width:40em;line-height:1.65}
.muted{color:var(--text-3);font-size:.9rem}
.mono{font-family:var(--mono)}
.section{padding:clamp(76px,10vw,136px) 0;position:relative}
.section-tight{padding:clamp(48px,6vw,80px) 0}
.section-head{max-width:760px;margin-bottom:clamp(36px,5vw,60px)}
.section-head .eyebrow{margin-bottom:18px}.section-head .lead{margin-top:18px}
.center{text-align:center;margin-left:auto;margin-right:auto}
.center .lead{margin-left:auto;margin-right:auto}
.divider{height:1px;background:linear-gradient(90deg,transparent,var(--border-2),transparent);
border:0;margin:0}
"""

NAV = """
.nav{position:sticky;top:0;z-index:50;border-bottom:1px solid transparent;
transition:background .35s,border-color .35s}
.nav.scrolled,.nav-solid{background:rgba(5,7,11,.74);border-bottom-color:rgba(255,255,255,.08);
backdrop-filter:saturate(170%) blur(18px);-webkit-backdrop-filter:saturate(170%) blur(18px)}
.nav-in{display:flex;align-items:center;gap:24px;height:70px}
.logo{display:inline-flex;align-items:center;gap:11px;text-decoration:none;font-weight:700;
font-size:1.14rem;letter-spacing:-.025em;color:#f4f6fb}
.logo .mark{width:30px;height:30px;transition:transform .5s var(--ease)}
.logo:hover .mark{transform:rotate(-8deg) scale(1.06)}
.nav-links{display:flex;gap:2px;margin-left:10px}
.nav-links a{text-decoration:none;color:#aab3c2;font-size:.9rem;font-weight:500;padding:8px 13px;
border-radius:999px;transition:color .2s,background .2s}
.nav-links a:hover{color:#fff;background:rgba(255,255,255,.07)}
.nav-end{margin-left:auto;display:flex;align-items:center;gap:10px}
.lang{font-size:.78rem;font-weight:650;letter-spacing:.06em;color:#c3cad6;text-decoration:none;
border:1px solid rgba(255,255,255,.16);padding:7px 11px;border-radius:999px;
transition:border-color .2s,color .2s}
.lang:hover{color:#fff;border-color:rgba(255,255,255,.4)}
.menu{display:none;position:relative}
.menu>summary{list-style:none;cursor:pointer;width:42px;height:42px;border-radius:12px;display:grid;
place-items:center;border:1px solid rgba(255,255,255,.16);transition:background .2s}
.menu>summary::-webkit-details-marker{display:none}
.menu>summary:hover{background:rgba(255,255,255,.07)}
.burger{display:grid;gap:4px;width:18px}
.burger i{display:block;height:2px;border-radius:2px;background:#f4f6fb;transition:transform .3s var(--ease),opacity .2s}
.menu[open] .burger i:nth-child(1){transform:translateY(6px) rotate(45deg)}
.menu[open] .burger i:nth-child(2){opacity:0}
.menu[open] .burger i:nth-child(3){transform:translateY(-6px) rotate(-45deg)}
.menu-panel{position:absolute;right:0;top:calc(100% + 10px);width:min(300px,calc(100vw - 32px));
display:grid;gap:2px;padding:10px;border-radius:18px;border:1px solid rgba(255,255,255,.14);
background:rgba(10,14,21,.97);box-shadow:0 30px 60px -20px rgba(0,0,0,.8);
backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);animation:drop .3s var(--ease)}
.menu-panel a{text-decoration:none;color:#dfe5ee;font-size:.98rem;padding:12px 14px;border-radius:12px}
.menu-panel a:hover{background:rgba(255,255,255,.07)}
.menu-panel .btn{margin-top:8px;color:#060914}
@media (max-width:900px){.nav-links{display:none}.menu{display:block}}
@media (max-width:520px){.nav-end>.lang{display:none}}
@media (max-width:520px){.nav-end>.btn{display:none}.nav-in{height:62px}}
"""

BUTTONS = """
.btn{--h:48px;position:relative;display:inline-flex;align-items:center;justify-content:center;
gap:10px;height:var(--h);padding:0 22px;border-radius:999px;font:600 .95rem/1 var(--sans);
letter-spacing:-.005em;text-decoration:none;border:0;cursor:pointer;color:#070a12;
background:#f4f6fb;overflow:hidden;isolation:isolate;white-space:nowrap;
transition:transform .3s var(--ease),box-shadow .3s,background .3s,color .3s;
box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 34px -14px rgba(154,168,255,.7)}
.btn::after{content:'';position:absolute;inset:0;z-index:-1;transform:translateX(-120%);
background:linear-gradient(110deg,transparent 25%,rgba(255,255,255,.7) 50%,transparent 75%);
transition:transform .9s var(--ease)}
.btn:hover{transform:translateY(-2px);box-shadow:0 1px 0 rgba(255,255,255,.5) inset,
0 20px 44px -16px rgba(154,168,255,.9)}
.btn:hover::after{transform:translateX(120%)}
.btn:active{transform:translateY(0) scale(.98)}
.btn svg{width:18px;height:18px;transition:transform .3s var(--ease)}
.btn:hover .go{transform:translateX(4px)}
.btn-primary{background:var(--grad);color:#060914}
.btn-ghost{background:transparent;color:var(--text);box-shadow:0 0 0 1px var(--border-2) inset}
.btn-ghost:hover{background:var(--surface-2);box-shadow:0 0 0 1px var(--border-2) inset}
.btn-ghost::after{display:none}
.btn-dark{background:#0a0d14;color:#f4f6fb;box-shadow:0 12px 30px -16px rgba(10,13,20,.8)}
.btn-sm{--h:38px;padding:0 16px;font-size:.86rem}
.btn-lg{--h:58px;padding:0 30px;font-size:1.02rem}
.btn-block{width:100%}
@media (max-width:620px){.hero-cta .btn{width:100%;white-space:normal;text-align:center}}
.btn[aria-busy=true]{pointer-events:none;opacity:.75}
"""

HERO = """
.hero{position:relative;overflow:hidden;padding:clamp(48px,8vw,104px) 0 clamp(64px,8vw,110px);
isolation:isolate}
.grid-bg{position:absolute;inset:0;z-index:-2;pointer-events:none;
background-image:linear-gradient(rgba(255,255,255,.05) 1px,transparent 1px),
linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px);background-size:68px 68px;
-webkit-mask-image:radial-gradient(ellipse 75% 60% at 50% 20%,#000 20%,transparent 72%);
mask-image:radial-gradient(ellipse 75% 60% at 50% 20%,#000 20%,transparent 72%)}
.aurora{position:absolute;inset:-30% -10% auto;height:130%;z-index:-1;pointer-events:none;
filter:blur(70px);opacity:.8}
.aurora span{position:absolute;border-radius:50%;animation:drift 20s ease-in-out infinite alternate}
.aurora span:nth-child(1){width:52vw;height:52vw;left:-12vw;top:-14vw;
background:radial-gradient(circle,rgba(91,108,255,.55),transparent 62%)}
.aurora span:nth-child(2){width:44vw;height:44vw;right:-10vw;top:-10vw;animation-duration:26s;
animation-delay:-8s;background:radial-gradient(circle,rgba(56,189,248,.34),transparent 62%)}
.aurora span:nth-child(3){width:34vw;height:34vw;left:34vw;top:16vw;animation-duration:30s;
background:radial-gradient(circle,rgba(110,231,216,.22),transparent 62%)}
.hero-grid{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr);gap:64px;
align-items:center}
@media (max-width:1000px){.hero-grid{grid-template-columns:minmax(0,1fr);gap:56px}}
.hero h1{font-size:clamp(2.7rem,5.6vw,5rem);margin:24px 0 24px}
.hero h1 .l{display:block}
.hero-cta{display:flex;flex-wrap:wrap;gap:12px;margin-top:36px}
.trust{display:flex;flex-wrap:wrap;gap:12px 26px;margin:40px 0 0;padding:0;list-style:none;
color:var(--text-2);font-size:.87rem}
.trust li{display:flex;align-items:center;gap:8px}
.trust svg{width:17px;height:17px;color:var(--accent-2);flex:none}
.rise{opacity:0;transform:translateY(20px);animation:rise 1s var(--ease) forwards;
animation-delay:calc(var(--i,0) * 90ms + 60ms)}
.page-hero{position:relative;overflow:hidden;isolation:isolate;padding:clamp(48px,7vw,88px) 0
clamp(44px,6vw,72px)}
.page-hero .aurora{opacity:.55}
.page-hero h1{font-family:var(--serif);font-weight:400;font-size:clamp(2.5rem,5.4vw,4.4rem);
letter-spacing:-.015em;line-height:1.02;margin:14px 0 16px}
.page-hero .lead{margin:0}
.crumbs{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;font-size:.86rem;
color:var(--text-3)}
.crumbs a{text-decoration:none;color:var(--text-2)}.crumbs a:hover{color:var(--text)}
"""

MOCK = """
.mock{position:relative;border-radius:var(--r-xl);padding:1px;
background:linear-gradient(160deg,rgba(255,255,255,.22),rgba(255,255,255,.04) 40%,
rgba(154,168,255,.35));box-shadow:0 60px 120px -50px rgba(40,56,160,.65),var(--shadow);
transform:perspective(1400px) rotateY(-7deg) rotateX(4deg);transition:transform .8s var(--ease)}
.mock:hover{transform:perspective(1400px) rotateY(-2deg) rotateX(1deg)}
.mock-in{border-radius:calc(var(--r-xl) - 1px);background:linear-gradient(180deg,#0e1420,#090d14);
overflow:hidden;position:relative}
.mock-top{display:flex;align-items:center;gap:12px;padding:14px 18px;
border-bottom:1px solid rgba(255,255,255,.07)}
.mock-top i{width:10px;height:10px;border-radius:50%;background:rgba(255,255,255,.14);display:block}
.mock-dots{display:flex;gap:6px}
.mock-url{margin-left:6px;font:500 .74rem var(--mono);color:#7f8898;background:rgba(255,255,255,.05);
padding:4px 10px;border-radius:999px}
.mock-body{padding:24px 24px 20px}
.mock-head{display:flex;gap:18px;align-items:center}
.mock-k{font-size:.7rem;letter-spacing:.14em;text-transform:uppercase;color:#7f8898;font-weight:600}
.mock-t{font-size:1rem;font-weight:550;color:#e8ecf3;line-height:1.35;margin-top:4px}
.spark{display:block;width:100%;height:auto;margin:20px 0 6px}
.spark-line{fill:none;stroke:url(#spg);stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round;
stroke-dasharray:1;stroke-dashoffset:1;animation:draw 2.4s var(--ease) .7s forwards}
.spark-area{fill:url(#spa);opacity:0;animation:fade 1.2s ease 1.8s forwards}
.spark-grid{stroke:rgba(255,255,255,.06);stroke-width:1}
.mock-dims{list-style:none;margin:10px 0 0;padding:0;display:grid;gap:2px}
.mock-dims li{display:flex;justify-content:space-between;align-items:center;gap:12px;
padding:9px 0;border-top:1px solid rgba(255,255,255,.06);font-size:.86rem;color:#c9d0db;
opacity:0;animation:rise .7s var(--ease) forwards;animation-delay:calc(var(--i) * 110ms + 1s)}
.mock-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:16px}
.mock-cap{position:absolute;right:16px;bottom:-30px;font-size:.74rem;color:var(--text-3)}
.float-chip{position:absolute;display:flex;align-items:center;gap:8px;padding:10px 14px;
border-radius:14px;background:rgba(14,20,32,.88);border:1px solid rgba(255,255,255,.12);
box-shadow:0 20px 40px -20px rgba(0,0,0,.8);font-size:.78rem;color:#dfe5ee;
backdrop-filter:blur(10px);animation:bob 6s ease-in-out infinite}
.float-chip svg{width:16px;height:16px;color:var(--accent-2)}
.fc-1{left:-24px;bottom:-30px}.fc-2{right:-26px;top:-20px;animation-delay:-3s}
@media (max-width:1000px){.mock{transform:none}.mock:hover{transform:none}.fc-1{left:8px}
.fc-2{right:8px}}
@media (max-width:560px){.float-chip{display:none}}
.ring{--p:0;position:relative;flex:none;width:86px;height:86px;border-radius:50%;display:grid;
place-items:center;background:conic-gradient(var(--c) calc(var(--p) * 1%),rgba(127,136,152,.18) 0);
animation:ring 1.8s var(--ease) .4s forwards}
.ring::before{content:'';position:absolute;inset:7px;border-radius:50%;background:var(--surface-solid)}
.ring .cls{position:relative;font-family:var(--serif);font-size:2.9rem;line-height:1;
font-weight:400;background:none;padding:0;margin:0}
.ring-lg{width:132px;height:132px}.ring-lg::before{inset:9px}.ring-lg .cls{font-size:4.6rem}
.ring-xl{width:168px;height:168px}.ring-xl::before{inset:11px}.ring-xl .cls{font-size:6rem}
"""

SECTIONS = """
.marquee{overflow:hidden;padding:26px 0;border-block:1px solid var(--border);
-webkit-mask-image:linear-gradient(90deg,transparent,#000 12%,#000 88%,transparent);
mask-image:linear-gradient(90deg,transparent,#000 12%,#000 88%,transparent)}
.marquee-track{display:flex;gap:64px;width:max-content;animation:marquee 42s linear infinite}
.marquee:hover .marquee-track{animation-play-state:paused}
.marquee-track span{display:flex;align-items:center;gap:12px;font-weight:600;font-size:1.05rem;
color:var(--text-2);white-space:nowrap;letter-spacing:-.01em}
.marquee-track span::before{content:'';width:6px;height:6px;border-radius:2px;background:var(--grad);
transform:rotate(45deg)}
.marquee-label{text-align:center;font-size:.74rem;letter-spacing:.14em;text-transform:uppercase;
color:var(--text-3);margin:0 0 18px;font-weight:600}
.cards{display:grid;gap:18px;grid-template-columns:repeat(3,minmax(0,1fr))}
.cards-2{grid-template-columns:repeat(2,minmax(0,1fr))}
.cards-4{grid-template-columns:repeat(4,minmax(0,1fr))}
@media (max-width:980px){.cards,.cards-4{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:640px){.cards,.cards-2,.cards-4{grid-template-columns:minmax(0,1fr)}}
.card{position:relative;border:1px solid var(--border);border-radius:var(--r-lg);
background:var(--surface);padding:28px;overflow:hidden;isolation:isolate;
transition:border-color .35s,transform .45s var(--ease),background .35s,box-shadow .35s}
.card:hover{border-color:var(--border-2);transform:translateY(-3px)}
.paper .card{box-shadow:0 1px 2px rgba(15,23,42,.04)}
.paper .card:hover{box-shadow:var(--shadow)}
.spot::before{content:'';position:absolute;inset:0;border-radius:inherit;z-index:-1;
pointer-events:none;opacity:0;transition:opacity .45s;
background:radial-gradient(460px circle at var(--mx,50%) var(--my,0%),rgba(154,168,255,.16),
transparent 45%)}
.spot:hover::before{opacity:1}
.card h3{font-size:1.1rem;font-weight:620;letter-spacing:-.012em;margin:20px 0 8px}
.card p{margin:0;color:var(--text-2);font-size:.95rem;line-height:1.6}
.icon{width:46px;height:46px;border-radius:13px;display:grid;place-items:center;
color:var(--accent);border:1px solid var(--border-2);
background:linear-gradient(180deg,rgba(255,255,255,.09),rgba(255,255,255,.015))}
.paper .icon{background:linear-gradient(180deg,#fff,#f1f3f8)}
.icon svg{width:22px;height:22px}
.num{font:500 .76rem var(--mono);color:var(--text-3);letter-spacing:.06em}
.big-num{font-family:var(--serif);font-size:clamp(3.6rem,6vw,5rem);line-height:.9;
background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent;
display:block}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;
border:1px solid var(--border);border-radius:var(--r-lg);overflow:hidden}
.stats div{padding:30px 26px;border-right:1px solid var(--border)}
.stats div:last-child{border-right:0}
.stats b{display:block;font-family:var(--serif);font-weight:400;font-size:clamp(2.6rem,4vw,3.4rem);
line-height:1;letter-spacing:-.02em}
.stats span{display:block;margin-top:10px;color:var(--text-2);font-size:.9rem}
@media (max-width:760px){.stats{grid-template-columns:1fr 1fr}.stats div:nth-child(2){border-right:0}
.stats div:nth-child(-n+2){border-bottom:1px solid var(--border)}}
.split{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:clamp(36px,6vw,88px);
align-items:start}
@media (max-width:900px){.split{grid-template-columns:minmax(0,1fr)}}
.sticky{position:sticky;top:110px}
@media (max-width:900px){.sticky{position:static}}
.tags{display:grid;gap:14px}
.tag-row{display:grid;grid-template-columns:170px 1fr;gap:20px;align-items:center;padding:22px 24px;
border:1px solid var(--border);border-radius:var(--r-lg);background:var(--surface)}
.tag-row p{margin:0;color:var(--text-2)}
@media (max-width:560px){.tag-row{grid-template-columns:minmax(0,1fr);gap:10px}}
.steps{counter-reset:s;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;
list-style:none;padding:0;margin:0;position:relative}
.steps::before{content:'';position:absolute;left:28px;right:28px;top:28px;height:1px;
background:linear-gradient(90deg,rgba(154,168,255,.6),rgba(110,231,216,.5),transparent)}
.steps li{position:relative;padding:0 6px 0 0;color:var(--text-2);font-size:.97rem}
.steps li::before{counter-increment:s;content:counter(s,decimal-leading-zero);display:grid;
place-items:center;width:56px;height:56px;border-radius:50%;margin-bottom:22px;
font:500 .86rem var(--mono);color:var(--text);background:var(--ink-3);
border:1px solid var(--border-2);box-shadow:0 0 0 8px var(--bg);position:relative}
@media (max-width:900px){.steps{grid-template-columns:1fr 1fr;gap:34px 18px}.steps::before{display:none}}
@media (max-width:560px){.steps{grid-template-columns:minmax(0,1fr)}}
.list-steps{counter-reset:s;list-style:none;padding:0;margin:0;display:grid;gap:12px}
.list-steps li{position:relative;padding:16px 18px 16px 62px;border:1px solid var(--border);
border-radius:var(--r);background:var(--surface);color:var(--text-2)}
.list-steps li::before{counter-increment:s;content:counter(s);position:absolute;left:16px;top:14px;
width:30px;height:30px;border-radius:50%;display:grid;place-items:center;
font:600 .8rem var(--mono);color:var(--text);border:1px solid var(--border-2)}
.checks{list-style:none;padding:0;margin:0;display:grid;gap:12px}
.checks li{display:flex;gap:12px;align-items:flex-start;color:var(--text-2);font-size:.95rem}
.checks li svg{width:18px;height:18px;flex:none;margin-top:3px;color:var(--accent-2)}
.paper .checks li svg{color:#0f9f8f}
.prices{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;max-width:960px}
.prices-one{grid-template-columns:minmax(0,1fr);max-width:560px}
@media (max-width:760px){.prices{grid-template-columns:minmax(0,1fr)}}
.price{position:relative;border:1px solid var(--border);border-radius:var(--r-xl);
background:var(--surface);padding:clamp(26px,3vw,38px);display:flex;flex-direction:column}
.price.featured{border-color:transparent;background:linear-gradient(#0c111b,#0c111b) padding-box,
linear-gradient(140deg,#9aa8ff,rgba(125,211,252,.4) 50%,#6ee7d8) border-box;
box-shadow:0 50px 100px -50px rgba(91,108,255,.7)}
.price-name{font-weight:600;color:var(--text-2);font-size:.95rem}
.price-amount{font-family:var(--serif);font-size:clamp(3rem,5vw,4.2rem);line-height:1;
margin:14px 0 6px;letter-spacing:-.02em}
.price-amount small{font-family:var(--sans);font-size:1rem;color:var(--text-3);margin-left:6px}
.price .checks{margin:24px 0 28px;flex:1}
.ribbon{position:absolute;top:22px;right:22px;font:600 .68rem var(--mono);letter-spacing:.08em;
text-transform:uppercase;padding:5px 10px;border-radius:999px;color:#060914;background:var(--grad)}
.pay-ways{margin:22px 0 0;max-width:960px}
.faq{max-width:860px}
.faq details{border-bottom:1px solid var(--border)}
.faq details:first-child{border-top:1px solid var(--border)}
.faq summary{list-style:none;cursor:pointer;padding:24px 48px 24px 0;font-weight:600;
font-size:1.06rem;position:relative;letter-spacing:-.01em;transition:color .2s}
.faq summary::-webkit-details-marker{display:none}
.faq summary:hover{color:var(--accent)}
.faq summary::after{content:'';position:absolute;right:8px;top:50%;width:14px;height:14px;
margin-top:-7px;transition:transform .35s var(--ease);
background:linear-gradient(currentColor,currentColor) center/14px 1.6px no-repeat,
linear-gradient(currentColor,currentColor) center/1.6px 14px no-repeat}
.faq details[open] summary::after{transform:rotate(45deg)}
.faq details p{margin:0 0 24px;color:var(--text-2);max-width:62em;animation:fade .5s ease}
.cta-band{position:relative;overflow:hidden;isolation:isolate;border-radius:var(--r-xl);
padding:clamp(40px,7vw,88px) clamp(24px,5vw,72px);border:1px solid var(--border-2);
background:radial-gradient(120% 140% at 0% 0%,rgba(91,108,255,.35),transparent 55%),
radial-gradient(120% 140% at 100% 100%,rgba(110,231,216,.22),transparent 55%),#0a0e16}
.cta-band .grid-bg{-webkit-mask-image:radial-gradient(ellipse at center,#000 10%,transparent 70%);
mask-image:radial-gradient(ellipse at center,#000 10%,transparent 70%)}
"""

FORMS = """
form{margin:0}
label,.label{display:block;font-weight:600;font-size:.88rem;margin:0 0 7px;color:var(--text)}
.field{margin:0 0 18px}
.help{color:var(--text-3);font-size:.83rem;margin-top:7px;line-height:1.5}
.help a{color:var(--text-2)}
input[type=text],input[type=number],input[type=email],input[type=date],select,textarea{width:100%;
height:48px;padding:0 15px;border-radius:12px;border:1px solid var(--border-2);
background:var(--field);color:var(--text);font:inherit;font-size:.95rem;
transition:border-color .2s,box-shadow .2s,background .2s;-webkit-appearance:none;appearance:none}
textarea{height:auto;min-height:96px;padding:13px 15px;resize:vertical}
select{padding-right:42px;background-repeat:no-repeat;background-position:right 15px center;
background-size:14px;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%237f8898' stroke-width='2.4' stroke-linecap='round'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")}
select option{background:#0c1119;color:#f4f6fb}
.paper select option{background:#fff;color:#0a0d14}
input:hover,select:hover,textarea:hover{border-color:rgba(154,168,255,.5)}
input:focus,select:focus,textarea:focus{outline:0;border-color:var(--accent);
box-shadow:0 0 0 4px rgba(154,168,255,.2)}
input::placeholder,textarea::placeholder{color:var(--text-3)}
input[type=date]::-webkit-calendar-picker-indicator{filter:invert(.7)}
.paper input[type=date]::-webkit-calendar-picker-indicator{filter:none}
.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}
@media (max-width:620px){.form-grid{grid-template-columns:minmax(0,1fr)}}
.check{display:flex;gap:13px;align-items:flex-start;font-weight:500;font-size:.9rem;
color:var(--text-2);line-height:1.55;cursor:pointer}
.check input{-webkit-appearance:none;appearance:none;width:22px;height:22px;flex:none;margin:1px 0 0;
border-radius:7px;border:1px solid var(--border-2);background:var(--field);display:grid;
place-items:center;cursor:pointer;transition:background .2s,border-color .2s}
.check input:checked{background:var(--grad);border-color:transparent}
.check input:checked::after{content:'';width:10px;height:5px;border:2.2px solid #060914;
border-top:0;border-right:0;transform:translateY(-1px) rotate(-45deg)}
.drop{position:relative;display:flex;align-items:center;gap:16px;padding:18px 20px;
border-radius:16px;border:1.5px dashed var(--border-2);background:var(--field);
transition:border-color .25s,background .25s,transform .25s var(--ease),box-shadow .25s}
.drop:hover,.drop.over{border-color:var(--accent);background:rgba(154,168,255,.07)}
.drop.over{transform:scale(1.012);box-shadow:0 0 0 6px rgba(154,168,255,.12)}
.drop.has{border-style:solid;border-color:rgba(110,231,216,.55);background:rgba(110,231,216,.06)}
.drop .icon{width:42px;height:42px;flex:none}
.drop-txt{min-width:0;flex:1}
.drop-title{font-weight:600;font-size:.94rem}
.drop-sub{color:var(--text-3);font-size:.82rem;margin-top:2px}
.drop-file{font:500 .8rem var(--mono);color:var(--accent-2);margin-top:4px;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.drop-file:empty{display:none}
.drop input[type=file]{font-size:.84rem;color:var(--text-2);max-width:100%;margin-top:8px}
.js .drop input[type=file]{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;
cursor:pointer}
.drop-main{flex-direction:column;text-align:center;padding:38px 24px;gap:12px;
background:radial-gradient(120% 120% at 50% 0%,rgba(154,168,255,.1),transparent 60%),var(--field)}
.drop-main .icon{width:56px;height:56px;border-radius:16px}
.drop-main .icon svg{width:26px;height:26px}
.drop-main .drop-title{font-size:1.08rem}
.drop-main.has .icon{color:var(--accent-2)}
.formats{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin-top:6px}
.formats span{font:500 .7rem var(--mono);padding:3px 8px;border-radius:6px;color:var(--text-2);
border:1px solid var(--border)}
details.adv{border:1px solid var(--border);border-radius:16px;margin:6px 0 20px;
background:rgba(255,255,255,.015)}
details.adv>summary{list-style:none;cursor:pointer;padding:16px 18px;display:flex;
align-items:center;justify-content:space-between;gap:12px;font-weight:600;font-size:.92rem}
details.adv>summary::-webkit-details-marker{display:none}
details.adv>summary small{font-weight:500;color:var(--text-3);font-size:.82rem}
details.adv>summary svg{width:16px;height:16px;transition:transform .3s var(--ease);flex:none}
details.adv[open]>summary svg{transform:rotate(180deg)}
.adv-body{padding:4px 18px 4px}
.upload{display:grid;grid-template-columns:minmax(0,.82fr) minmax(0,1.18fr);
gap:clamp(32px,5vw,72px);align-items:start}
@media (max-width:960px){.upload{grid-template-columns:minmax(0,1fr)}}
.panel{position:relative;border:1px solid var(--border-2);border-radius:var(--r-xl);
padding:clamp(22px,3.2vw,38px);box-shadow:var(--shadow);
background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,.02)),#090d14}
.panel::before{content:'';position:absolute;inset:-1px;border-radius:inherit;padding:1px;
pointer-events:none;background:linear-gradient(160deg,rgba(154,168,255,.55),transparent 35%,
transparent 65%,rgba(110,231,216,.4));-webkit-mask:linear-gradient(#000 0 0) content-box,
linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude}
.panel-note{display:flex;gap:10px;align-items:center;font-size:.85rem;color:var(--text-2);
margin:0 0 20px}
.panel-note svg{width:16px;height:16px;color:var(--accent-2);flex:none}
.submit-row{margin-top:22px}
.inline-form{display:flex;flex-wrap:wrap;gap:10px}
.inline-form input{flex:1 1 220px}
.busy{position:fixed;inset:0;z-index:90;display:none;place-items:center;padding:24px;
background:rgba(5,7,11,.84);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px)}
.busy.on{display:grid;animation:fade .35s ease}
.busy-card{width:100%;max-width:420px;text-align:center;color:#f4f6fb}
.busy-card h2{font-family:var(--serif);font-weight:400;font-size:2.2rem;margin:0 0 6px}
.loader{width:72px;height:72px;margin:0 auto 26px;border-radius:50%;
background:conic-gradient(from 0deg,transparent 0 20%,#9aa8ff,#6ee7d8);
-webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 5px),#000 calc(100% - 4px));
mask:radial-gradient(farthest-side,transparent calc(100% - 5px),#000 calc(100% - 4px));
animation:spin 1.1s linear infinite}
.busy ol{list-style:none;padding:0;margin:26px 0 0;display:grid;gap:12px;text-align:left}
.busy li{display:flex;gap:12px;align-items:center;color:#b6bfcc;opacity:.25;font-size:.95rem;
animation:on .6s var(--ease) forwards;animation-delay:calc(var(--i) * 1.3s + .3s)}
.busy li::before{content:'';width:8px;height:8px;border-radius:50%;background:var(--grad);flex:none}
"""

ALERTS = """
.flash,.error,.notice,.banner,.warning{border-radius:14px;padding:13px 16px;margin:14px 0;
font-size:.92rem;border:1px solid;line-height:1.5}
.flash{color:var(--ok);background:rgba(34,197,94,.09);border-color:rgba(34,197,94,.3)}
.error{color:var(--bad);background:rgba(239,68,68,.08);border-color:rgba(239,68,68,.3)}
.notice{color:var(--info);background:rgba(129,140,248,.1);border-color:rgba(129,140,248,.32);
font-weight:600}
.banner{color:var(--warn);background:rgba(245,158,11,.09);border-color:rgba(245,158,11,.32);
font-weight:650;letter-spacing:.02em}
.disclaimer{border:1px solid var(--border);border-radius:16px;padding:18px 20px;
background:var(--surface-2);color:var(--text-2);font-size:.86rem;line-height:1.6;margin:0}
.disclaimer strong{color:var(--text)}
"""

FOOTER = """
.foot{--bg:var(--ink);--text:#f4f6fb;--text-2:#b6bfcc;--text-3:#7f8898;
--border:rgba(255,255,255,.09);--border-2:rgba(255,255,255,.17);--surface-2:rgba(255,255,255,.04);
background:var(--ink);color:var(--text-2);border-top:1px solid var(--border);
padding:clamp(56px,7vw,88px) 0 40px;color-scheme:dark}
.foot-grid{display:grid;grid-template-columns:1.5fr 1fr 1fr;gap:40px;margin-bottom:44px}
@media (max-width:760px){.foot-grid{grid-template-columns:1fr 1fr}.foot-grid>div:first-child{
grid-column:1/-1}}
.foot h4{font-size:.74rem;letter-spacing:.14em;text-transform:uppercase;color:var(--text-3);
margin:0 0 16px;font-weight:600}
.foot ul{list-style:none;margin:0;padding:0;display:grid;gap:10px;font-size:.92rem}
.foot a{text-decoration:none;color:var(--text-2)}.foot a:hover{color:#fff}
.foot .tagline{margin:14px 0 0;max-width:32em;font-size:.92rem}
.foot .legal{margin:22px 0 0;font-size:.84rem}
.foot-base{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;margin-top:28px;
font-size:.8rem;color:var(--text-3)}
.news{margin-top:22px;max-width:420px}
.news .inline-form input{height:44px}
"""

REPORT = """
.report-hero{position:relative;overflow:hidden;isolation:isolate;padding:28px 0 56px}
.report-hero .aurora{opacity:.5}
.toolbar{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;
margin-bottom:34px}
.toolbar-end{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.print-btn{display:inline-flex;align-items:center;gap:8px;height:38px;padding:0 16px;
border-radius:999px;border:1px solid var(--border-2);background:rgba(255,255,255,.04);
color:var(--text);font:600 .86rem var(--sans);cursor:pointer;transition:background .2s}
.print-btn:hover{background:rgba(255,255,255,.1)}
.lang-switch{font-size:.86rem;font-weight:600;text-decoration:none;color:var(--text-2);
padding:8px 14px;border-radius:999px;border:1px solid var(--border-2)}
.lang-switch:hover{color:var(--text)}
.report-hero h1{font-family:var(--serif);font-weight:400;font-size:clamp(2.4rem,5vw,4rem);
letter-spacing:-.015em;line-height:1.02;margin:14px 0 12px}
.meta-line{display:flex;flex-wrap:wrap;gap:8px;margin:0}
.meta-line span{font:500 .76rem var(--mono);color:var(--text-2);padding:5px 10px;border-radius:8px;
background:rgba(255,255,255,.05);border:1px solid var(--border)}
.verdict{display:flex;gap:30px;align-items:center;margin:34px 0 0;padding:clamp(22px,3vw,34px);
border-radius:var(--r-xl);border:1px solid var(--border-2);box-shadow:var(--shadow);
background:linear-gradient(180deg,rgba(255,255,255,.07),rgba(255,255,255,.02)),#0a0f18}
.verdict-k{font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--text-3);
font-weight:600;margin-bottom:8px}
.verdict-text{font-size:clamp(1.05rem,1.6vw,1.28rem);line-height:1.5;color:#e8ecf3;margin:0}
@media (max-width:620px){.verdict{flex-direction:column;align-items:flex-start;gap:20px}}
.report-main{padding:clamp(40px,6vw,72px) 0 clamp(56px,8vw,96px)}
.rsec{margin:0 0 clamp(36px,5vw,56px)}
.rsec>h2,.detail>h2{font-size:1.45rem;font-weight:650;letter-spacing:-.02em;margin:0 0 18px;
display:flex;align-items:center;gap:12px}
.rsec>h2::before,.detail>h2::before{content:'';width:4px;height:22px;border-radius:4px;
background:linear-gradient(180deg,#5b6cff,#2dd4bf);flex:none}
.detail{margin:0 0 clamp(32px,4vw,48px)}
.rsec h3,.detail h3{font-size:1.02rem;margin:22px 0 10px;font-weight:620}
.paper table{width:100%;border-collapse:separate;border-spacing:0;font-size:.88rem;
margin:.4em 0 1.2em;border:1px solid var(--border);border-radius:14px;overflow:hidden;
font-variant-numeric:tabular-nums;background:#fff}
table{border-collapse:collapse}
th,td{padding:11px 14px;text-align:left;vertical-align:top;border-bottom:1px solid var(--border)}
.paper tr:last-child>td{border-bottom:0}
th{background:var(--surface-2);font-weight:600;font-size:.74rem;text-transform:uppercase;
letter-spacing:.06em;color:var(--text-2)}
.paper tr:hover>td{background:#fafbfd}
.badge{display:inline-flex;align-items:center;gap:6px;padding:3px 10px 3px 8px;border-radius:999px;
font:600 .68rem/1.5 var(--mono);letter-spacing:.02em;border:1px solid transparent;
white-space:nowrap;vertical-align:middle}
.badge::before{content:'';width:6px;height:6px;border-radius:50%;background:currentColor;flex:none}
.MEASURED,.PASS{color:var(--ok);background:rgba(34,197,94,.1);border-color:rgba(34,197,94,.3)}
.DECLARED,.WEAK,.WARN{color:var(--warn);background:rgba(245,158,11,.1);
border-color:rgba(245,158,11,.32)}
.FAIL,.ERROR{color:var(--bad);background:rgba(239,68,68,.09);border-color:rgba(239,68,68,.3)}
.NOT_MEASURED,.NOT_APPLICABLE,.INFO{color:var(--text-3);background:rgba(127,136,152,.1);
border-color:rgba(127,136,152,.3)}
.status{display:inline-flex;padding:3px 10px;border-radius:999px;font-size:.78rem;font-weight:600;
background:var(--surface-2);border:1px solid var(--border)}
.meaning{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:0}
@media (max-width:760px){.meaning{grid-template-columns:minmax(0,1fr)}}
.meaning .item{position:relative;border:1px solid var(--border);border-radius:18px;
padding:20px 22px 18px;background:#fff;overflow:hidden;transition:box-shadow .3s,transform .3s}
.meaning .item:hover{box-shadow:var(--shadow);transform:translateY(-2px)}
.meaning .item h3{font-size:1rem;margin:0 0 10px;display:flex;flex-wrap:wrap;
justify-content:space-between;gap:8px;align-items:center;font-weight:620}
.meaning .item p{margin:0;color:var(--text-2);font-size:.92rem}
.meaning .item::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;
background:var(--sc,#cbd5e1)}
.meaning .s-PASS{--sc:#22c55e}.meaning .s-WEAK{--sc:#f59e0b}.meaning .s-FAIL{--sc:#ef4444}
.flag-list{list-style:none;padding:0;margin:0;display:grid;gap:8px}
.flag-list li{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:12px 14px;
border:1px solid var(--border);border-radius:12px;background:#fff}
.watermark{position:fixed;top:42%;left:4%;right:4%;text-align:center;font-size:clamp(2.4rem,7vw,5.4rem);
font-weight:800;letter-spacing:.04em;color:rgba(220,38,38,.09);transform:rotate(-22deg);
pointer-events:none;z-index:9}
.lockbox{position:relative;overflow:hidden;isolation:isolate;border-radius:var(--r-xl);
padding:clamp(26px,4vw,44px);margin:0 0 40px;color:#f4f6fb;
background:radial-gradient(120% 120% at 100% 0%,rgba(91,108,255,.4),transparent 55%),
radial-gradient(100% 100% at 0% 100%,rgba(110,231,216,.2),transparent 55%),#0a0e16;
--text:#f4f6fb;--text-2:#b6bfcc;--text-3:#7f8898;--border:rgba(255,255,255,.12);
--border-2:rgba(255,255,255,.2);--field:rgba(255,255,255,.05);--accent:#9aa8ff;color-scheme:dark}
.lockbox>p:first-child{font-family:var(--serif);font-size:clamp(1.6rem,3vw,2.2rem);line-height:1.15;
margin:0 0 20px;color:#fff}
.lockbox ul{list-style:none;padding:0;margin:0 0 26px;display:grid;
grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 22px}
@media (max-width:620px){.lockbox ul{grid-template-columns:minmax(0,1fr)}}
.lockbox li{display:flex;gap:10px;align-items:center;color:#c9d0db;font-size:.92rem}
.lockbox li::before{content:'';width:14px;height:14px;flex:none;opacity:.7;
background:no-repeat center/contain url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%239aa8ff' stroke-width='2' stroke-linecap='round'%3E%3Crect x='5' y='11' width='14' height='10' rx='2'/%3E%3Cpath d='M8 11V8a4 4 0 018 0v3'/%3E%3C/svg%3E")}
.paybox{margin:12px 0 0;padding:18px;border-radius:18px;border:1px solid var(--border);
background:rgba(255,255,255,.04)}
.paybox label{color:#e8ecf3}
.paybox .inline-form{margin-top:8px}
.paybox a{color:#fff;font-weight:600}
.publish{display:flex;flex-wrap:wrap;gap:18px;align-items:center;justify-content:space-between;
padding:24px 26px;border-radius:var(--r-lg);border:1px solid var(--border);
background:linear-gradient(180deg,#fff,#f6f7fb);margin:0 0 36px}
.publish p{margin:0;max-width:40em}
.report-foot{display:grid;gap:14px}
"""

VERIFY = """
.v-hero{display:grid;grid-template-columns:auto minmax(0,1fr);gap:clamp(24px,4vw,48px);
align-items:center}
@media (max-width:620px){.v-hero{grid-template-columns:minmax(0,1fr)}}
.v-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:26px}
@media (max-width:760px){.v-facts{grid-template-columns:minmax(0,1fr)}}
.v-facts div{padding:14px 16px;border-radius:14px;border:1px solid var(--border);
background:rgba(255,255,255,.04)}
.v-facts b{display:block;font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;
color:var(--text-3);font-weight:600;margin-bottom:4px}
.v-facts span{font:500 .86rem var(--mono);color:var(--text);word-break:break-all}
.badge-preview{padding:28px;border-radius:var(--r-lg);border:1px solid var(--border);
background:repeating-conic-gradient(#f4f5f8 0 25%,#fff 0 50%) 0 0/18px 18px;text-align:center}
.copy-row{display:flex;justify-content:flex-end;margin-top:10px}
.guide-list{list-style:none;padding:0;margin:0;display:grid;gap:14px;
grid-template-columns:repeat(2,minmax(0,1fr))}
@media (max-width:700px){.guide-list{grid-template-columns:minmax(0,1fr)}}
.guide-list a{display:flex;flex-direction:column;gap:6px;height:100%;padding:22px 24px;
border-radius:var(--r-lg);border:1px solid var(--border);background:#fff;text-decoration:none;
transition:box-shadow .3s,transform .3s var(--ease),border-color .3s}
.guide-list a:hover{box-shadow:var(--shadow);transform:translateY(-3px);border-color:var(--border-2)}
.guide-list b{font-size:1.04rem;font-weight:620;display:flex;justify-content:space-between;gap:10px}
.guide-list b svg{width:18px;height:18px;color:var(--accent);transition:transform .3s var(--ease)}
.guide-list a:hover b svg{transform:translateX(4px)}
.guide-list span{color:var(--text-2);font-size:.92rem}
.prose{max-width:760px}
.prose h2{font-size:1.3rem;font-weight:650;letter-spacing:-.015em;margin:2.2em 0 .7em}
.prose h2:first-child{margin-top:0}
.prose p,.prose li{color:var(--text-2)}
.prose ul{padding-left:1.2em}.prose li{margin:.35em 0}
.page-main{padding:clamp(44px,6vw,80px) 0 clamp(64px,9vw,112px)}
.back-row{display:flex;flex-wrap:wrap;gap:12px;margin-top:40px}
"""

MOTION = """
[data-reveal]{transition:opacity 1s var(--ease),transform 1s var(--ease);
transition-delay:calc(var(--i,0) * 80ms)}
.js [data-reveal]:not(.in){opacity:0;transform:translateY(28px)}
@keyframes rise{to{opacity:1;transform:none}}
@keyframes drop{from{opacity:0;transform:translateY(-8px)}}
@keyframes fade{from{opacity:0}to{opacity:1}}
@keyframes on{to{opacity:1;color:#f4f6fb}}
@keyframes draw{to{stroke-dashoffset:0}}
@keyframes ring{to{--p:var(--to)}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes marquee{to{transform:translateX(-50%)}}
@keyframes pulse{0%,100%{box-shadow:0 0 0 4px rgba(110,231,216,.16)}
50%{box-shadow:0 0 0 8px rgba(110,231,216,0)}}
@keyframes drift{0%{transform:translate3d(0,0,0) scale(1)}
100%{transform:translate3d(6vw,4vw,0) scale(1.15)}}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;
animation-delay:0s!important;animation-iteration-count:1!important;transition-duration:.01ms!important;
scroll-behavior:auto!important}.js [data-reveal]:not(.in){opacity:1;transform:none}
.marquee-track{animation:none}.aurora span{animation:none}}
"""

PRINT = """
@media print{
:root,.hero,.page-hero,.report-hero,.lockbox,.verdict{--bg:#fff;--surface:#fff;--surface-2:#f4f5f8;
--surface-solid:#fff;--text:#000;--text-2:#333;--text-3:#555;--border:#ddd;--border-2:#ccc;
--ok:#15803d;--warn:#b45309;--bad:#b91c1c;color-scheme:light}
body,.report-hero,.verdict,.lockbox{background:#fff!important;color:#000!important;
box-shadow:none!important}
.nav,.no-print,.paybox,.print-btn,.publish,.aurora,.grid-bg,.foot,.busy,.lang-switch{
display:none!important}
.report-hero{padding:0}.report-main{padding:12px 0}
.wrap{max-width:none;padding:0}body{font-size:10.5pt}
.verdict-text,.report-hero h1,.lockbox>p:first-child{color:#000!important}
[data-reveal],.rise{opacity:1!important;transform:none!important;animation:none!important}
.ring{--p:var(--to);animation:none}
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
    return "<div class='aurora' aria-hidden='true'><span></span><span></span><span></span></div>"


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
