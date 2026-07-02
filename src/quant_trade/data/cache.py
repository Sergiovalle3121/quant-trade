"""Local CSV cache for normalized historical datasets."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_trade.data.manifest import build_manifest, write_manifest
from quant_trade.data.requests import HistoricalDataRequest
from quant_trade.data.validation import validate_ohlcv


def cache_file_path(request: HistoricalDataRequest, symbol: str | None = None) -> Path:
    symbols = symbol or (
        request.symbols[0] if len(request.symbols) == 1 else "_".join(request.symbols)
    )
    adj = "adjusted" if request.adjusted else "unadjusted"
    name = f"{symbols}_{request.start.isoformat()}_{request.end.isoformat()}_{adj}.csv"
    return Path(request.output_dir) / request.provider / symbols / request.interval / name


def write_cache(
    data: pd.DataFrame, request: HistoricalDataRequest, warnings: list[str] | None = None
) -> Path:
    path = cache_file_path(request)
    if path.exists() and not request.force_refresh:
        raise FileExistsError(f"cache file already exists (use --force-refresh): {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    valid = validate_ohlcv(data)
    valid.to_csv(path, index=False)
    write_manifest(path, build_manifest(path, valid, request, warnings or []))
    return path


def read_cache(path: str | Path) -> pd.DataFrame:
    data = pd.read_csv(path)
    return validate_ohlcv(data)


def list_cache(output_dir: str | Path = "data/cache", provider: str | None = None) -> list[Path]:
    root = Path(output_dir) / provider if provider else Path(output_dir)
    if not root.exists():
        return []
    return sorted(root.rglob("*.csv"))
