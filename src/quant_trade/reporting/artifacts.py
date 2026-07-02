from pathlib import Path
import json
import yaml
import pandas as pd


def create_run_dir(base: str | Path, name: str) -> Path:
    root = Path(base)
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / name
    if not candidate.exists():
        candidate.mkdir()
        return candidate
    i = 1
    while (root / f"{name}_{i:03d}").exists():
        i += 1
    candidate = root / f"{name}_{i:03d}"
    candidate.mkdir()
    return candidate


def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def write_yaml(path: Path, data: dict):
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def write_csv(path: Path, df: pd.DataFrame):
    df.to_csv(path, index=False)


def write_summary(path: Path, title: str, lines: list[str]):
    path.write_text("# " + title + "\n\n" + "\n".join(lines) + "\n")
