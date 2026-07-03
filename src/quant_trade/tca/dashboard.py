"""Static dashboard support for offline TCA artifacts."""
from pathlib import Path


def dashboard_path(output_dir: Path) -> Path:
    return output_dir / "dashboard" / "index.html"
