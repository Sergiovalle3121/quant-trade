from pathlib import Path


def write_dashboard(path: Path, status: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    html = (
        "<html><body><h1>Security Dashboard</h1>"
        f"<p>Status: {status}</p><p>real_money_ready=false</p></body></html>"
    )
    (path / "index.html").write_text(html, encoding="utf-8")
