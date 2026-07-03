from __future__ import annotations

from pathlib import Path

from .config import load_yaml, output_dir
from .dossier import build_dossier


def write_dashboard(config_path: Path) -> Path:
    cfg = load_yaml(config_path)
    out = output_dir(cfg) / "dashboard"
    out.mkdir(parents=True, exist_ok=True)
    d = build_dossier(cfg).to_dict()
    html = "".join(
        [
            "<!doctype html><html><body><h1>Paper Readiness Dashboard</h1>",
            f"<p>Final status: {d['final_status']}</p>",
            "<p>real_money_ready: false</p>",
            "<p>real_money_approved: false</p>",
            "<p>live_trading_enabled: false</p>",
            "</body></html>",
        ]
    )
    p = out / "index.html"
    p.write_text(html, encoding="utf-8")
    return p
