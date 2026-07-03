from __future__ import annotations

from pathlib import Path


def write_markdown(path: Path, title: str, body: str) -> None:
    path.write_text(f"# {title}\n\n{body}\n\nreal_money_ready: false\n", encoding="utf-8")
