"""Optional, credential-free personal research snapshots; no broker calls.

Yahoo data may be delayed or revised. Only closed daily bars are accepted;
these snapshots are not a real-time execution feed. Files are private caches.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.data.panel import validate_panel_schema

UNIVERSE = ("SPY", "QQQ", "IWM", "TLT", "GLD")


def _calendar(start: str, end: str) -> pd.DataFrame:
    try:
        import exchange_calendars as xcals
    except ImportError as exc:
        raise ImportError("install quant-trade[personal-paper] for NYSE calendars") from exc
    calendar = xcals.get_calendar("XNYS", start=start, end=end)
    schedule = calendar.schedule.copy()
    return pd.DataFrame(
        {
            "session_date": [str(pd.Timestamp(value).date()) for value in schedule.index],
            "session_open_utc": pd.to_datetime(schedule["open"], utc=True).to_numpy(),
            "session_close_utc": pd.to_datetime(schedule["close"], utc=True).to_numpy(),
        }
    )


def normalize_history(
    raw: pd.DataFrame,
    symbol: str,
    schedule: pd.DataFrame,
    observed_at: pd.Timestamp,
    *,
    received_at: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if symbol not in UNIVERSE or raw.empty:
        raise ValueError("empty history or unsupported fixed-universe symbol")
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    received = observed_at if received_at is None else received_at
    if received.tzinfo is None or received < observed_at:
        raise ValueError("received_at must be timezone-aware and not precede the cutoff")
    required = {"Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"}
    if not required.issubset(raw.columns):
        raise ValueError("history requires explicit OHLCV, dividends and stock splits")
    rows = raw.copy()
    rows["session_date"] = [str(pd.Timestamp(value).date()) for value in rows.index]
    rows = rows.reset_index(drop=True).merge(schedule, on="session_date", how="left")
    if rows.session_close_utc.isna().any():
        raise ValueError("history contains a date outside the exchange calendar")
    # Yahoo OHLC is split-adjusted even with auto_adjust=False. Restore
    # pre-split share units before applying explicit splits in the simulator.
    # This keeps a later snapshot from changing earlier recorded raw prices.
    splits = pd.to_numeric(rows["Stock Splits"], errors="raise").replace(0, 1)
    if not np.isfinite(splits).all() or (splits <= 0).any():
        raise ValueError("invalid corporate action")
    future_splits = splits.iloc[::-1].cumprod().iloc[::-1] / splits
    for name in ("Open", "High", "Low", "Close", "Dividends"):
        if name in rows:
            rows[name] = rows[name] * future_splits
    closes = pd.to_datetime(rows.session_close_utc, utc=True)
    rows = rows.loc[closes <= observed_at].copy()
    if rows.empty:
        raise ValueError("no closed daily bars available")
    rows["timestamp"] = pd.to_datetime(rows.session_date, utc=True)
    rows["bar_end_utc"] = pd.to_datetime(rows.session_close_utc, utc=True)
    rows["observed_at_utc"] = received
    rows["symbol"] = symbol
    rows = rows.rename(
        columns={name: name.lower() for name in ("Open", "High", "Low", "Close", "Volume")}
    )
    rows["dividend"] = rows["Dividends"]
    rows["split_ratio"] = rows["Stock Splits"].replace(0, 1)
    numeric = ["open", "high", "low", "close", "volume", "dividend", "split_ratio"]
    for name in numeric:
        rows[name] = pd.to_numeric(rows[name], errors="raise")
    if not np.isfinite(rows[numeric].to_numpy(dtype=float)).all():
        raise ValueError("non-finite market data")
    if (rows.dividend < 0).any() or (rows.split_ratio <= 0).any():
        raise ValueError("invalid corporate action")
    columns = [
        "timestamp",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "dividend",
        "split_ratio",
        "bar_end_utc",
        "observed_at_utc",
    ]
    return validate_panel_schema(rows[columns])


def normalize_fx(raw: pd.DataFrame, observed_at: pd.Timestamp) -> pd.DataFrame:
    if raw.empty:
        raise ValueError("Yahoo returned no USD/MXN observations")
    records = []
    for stamp, row in raw.iterrows():
        date = pd.Timestamp(stamp).date()
        # Daily FX has no exchange close contract. Admit only completed UTC
        # dates, conservatively one day later, never today's evolving value.
        end = pd.Timestamp(date, tz="UTC") + pd.Timedelta(days=1)
        if end > observed_at:
            continue
        value = float(row["Close"])
        if not np.isfinite(value) or value <= 0:
            raise ValueError("USD/MXN must be finite and positive")
        records.append(
            {
                "timestamp": end.isoformat(),
                "usd_mxn": value,
                "source": "Yahoo Finance MXN=X via yfinance; delayed research data",
            }
        )
    if not records:
        raise ValueError("no completed USD/MXN daily observations")
    result = pd.DataFrame(records)
    if result.timestamp.duplicated().any():
        raise ValueError("duplicate USD/MXN observations")
    return result.sort_values("timestamp").reset_index(drop=True)


def normalize_open_quote(
    raw: pd.DataFrame,
    symbol: str,
    schedule: pd.DataFrame,
    observed_at: pd.Timestamp,
    *,
    received_at: pd.Timestamp | None = None,
) -> dict[str, Any] | None:
    """Admit only a completed one-minute price in the actual opening window.

    Price timestamp is the minute's end, not the retrieval time. Yahoo may
    deliver late; callers must wait rather than relabel old prices as fresh.
    """
    received = observed_at if received_at is None else received_at
    if observed_at.tzinfo is None or received.tzinfo is None or received < observed_at:
        raise ValueError("quote cutoff and receipt must be timezone-aware and ordered")
    opens = pd.to_datetime(schedule.session_open_utc, utc=True)
    closes = pd.to_datetime(schedule.session_close_utc, utc=True)
    current = schedule.loc[(opens <= observed_at) & (closes > observed_at)]
    if current.empty or raw.empty:
        return None
    if not {"Volume", "Dividends", "Stock Splits", "Close"}.issubset(raw.columns):
        return None
    session = current.iloc[-1]
    opening, closing = (
        pd.Timestamp(session.session_open_utc),
        pd.Timestamp(session.session_close_utc),
    )
    if (received - opening).total_seconds() > 300:
        return None
    index = pd.DatetimeIndex(raw.index)
    if index.tz is None:
        raise ValueError("intraday quote timestamps must include the provider timezone")
    ends = index.tz_convert("UTC") + pd.Timedelta(minutes=1)
    eligible = raw.loc[(ends <= observed_at) & (ends > opening)]
    if eligible.empty:
        return None
    timestamp = pd.Timestamp(eligible.index[-1]).tz_convert("UTC") + pd.Timedelta(minutes=1)
    if (observed_at - timestamp).total_seconds() > 300:
        return None
    price = float(eligible.iloc[-1]["Close"])
    if not np.isfinite(price) or price <= 0:
        raise ValueError("opening quote price must be finite and positive")
    volume = float(eligible.iloc[-1]["Volume"])
    dividends = pd.to_numeric(eligible["Dividends"], errors="raise")
    splits = pd.to_numeric(eligible["Stock Splits"], errors="raise").replace(0, 1)
    if (
        not np.isfinite(volume)
        or volume <= 0
        or not np.isfinite(dividends).all()
        or not np.isfinite(splits).all()
        or (dividends < 0).any()
        or (splits <= 0).any()
    ):
        return None
    prior = schedule.loc[closes < opening]
    if prior.empty:
        raise ValueError("calendar does not contain the previous session")
    return {
        "symbol": symbol,
        "price": price,
        "available_volume": volume,
        "dividend": float(dividends.sum()),
        "split_ratio": float(splits.prod()),
        "observed_at_utc": timestamp.isoformat(),
        "received_at_utc": received.isoformat(),
        "session_open_utc": opening.isoformat(),
        "session_close_utc": closing.isoformat(),
        "previous_session_date": str(prior.iloc[-1].session_date),
        "source": "Yahoo completed 1m bar close; delayed hypothetical execution",
    }


def fetch_open_quotes(cache_dir: Path, *, as_of: str | None = None) -> Path | None:
    import yfinance as yf

    observed = pd.Timestamp(datetime.now(UTC)) if as_of is None else pd.Timestamp(as_of)
    if observed.tzinfo is None or observed > pd.Timestamp(datetime.now(UTC)):
        raise ValueError("quote as_of must be timezone-aware and not future")
    schedule = _calendar(
        (observed - pd.Timedelta(days=10)).date().isoformat(),
        (observed + pd.Timedelta(days=2)).date().isoformat(),
    )
    opens = pd.to_datetime(schedule.session_open_utc, utc=True)
    active = (opens <= observed) & ((observed - opens) <= pd.Timedelta(seconds=300))
    if not active.any():
        return None
    quotes = []
    for symbol in UNIVERSE:
        raw = yf.Ticker(symbol).history(
            period="1d",
            interval="1m",
            auto_adjust=False,
            actions=True,
            prepost=False,
            raise_errors=True,
        )
        received = pd.Timestamp(datetime.now(UTC))
        quote = normalize_open_quote(raw, symbol, schedule, observed, received_at=received)
        if quote is None:
            return None
        quotes.append(quote)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / (observed.strftime("quotes-%Y%m%dT%H%M%S%fZ") + ".csv")
    pd.DataFrame(quotes).to_csv(path, index=False)
    return path


def fetch_snapshot(start: str, cache_dir: Path, *, as_of: str | None = None) -> Path:
    """Fetch all five ETFs and FX before atomically publishing a snapshot index.

    Any missing symbol fails the whole fetch. A past as_of is development
    only because retrieval cannot prove what the provider knew in that past.
    """
    import yfinance as yf

    observed = pd.Timestamp(datetime.now(UTC))
    cutoff = pd.Timestamp(as_of) if as_of else observed
    if cutoff.tzinfo is None or cutoff > observed:
        raise ValueError("as_of must be timezone-aware and cannot be in the future")
    end = (cutoff + pd.Timedelta(days=2)).date().isoformat()
    schedule = _calendar(start, end)
    frames = []
    for symbol in UNIVERSE:
        raw = yf.Ticker(symbol).history(
            start=start, end=end, interval="1d", auto_adjust=False, actions=True, raise_errors=True
        )
        received = pd.Timestamp(datetime.now(UTC))
        frames.append(normalize_history(raw, symbol, schedule, cutoff, received_at=received))
    panel = pd.concat(frames, ignore_index=True)
    sessions = [set(frame.timestamp) for frame in frames]
    if any(dates != sessions[0] for dates in sessions[1:]):
        raise ValueError("incomplete fixed-universe panel: symbol coverage differs")
    expected = set(
        pd.to_datetime(
            schedule.loc[
                pd.to_datetime(schedule.session_close_utc, utc=True) <= cutoff, "session_date"
            ],
            utc=True,
        )
    )
    if sessions[0] != expected:
        raise ValueError("missing exchange sessions; refusing silent gap filling")
    fx_start = (pd.Timestamp(start) - pd.Timedelta(days=7)).date().isoformat()
    fx = normalize_fx(
        yf.Ticker("MXN=X").history(
            start=fx_start, end=end, interval="1d", auto_adjust=False, raise_errors=True
        ),
        cutoff,
    )
    retrieved = pd.Timestamp(datetime.now(UTC))
    stamp = retrieved.strftime("%Y%m%dT%H%M%S%fZ")
    output = cache_dir / stamp
    output.mkdir(parents=True, exist_ok=False)
    documents = {
        "panel.csv": panel,
        "fx.csv": fx,
        "calendar.csv": schedule.drop(columns=["session_date"]),
    }
    digests = {}
    for name, frame in documents.items():
        path = output / name
        frame.to_csv(path, index=False)
        digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest: dict[str, Any] = {
        "provider": "Yahoo Finance via yfinance",
        "retrieved_at_utc": retrieved.isoformat(),
        "as_of_utc": cutoff.isoformat(),
        "universe": list(UNIVERSE),
        "interval": "1d",
        "price_basis": "unadjusted OHLCV; explicit dividends and split ratios",
        "evidence_kind": "DEVELOPMENT",
        "files_sha256": digests,
        "versions": {
            name: importlib.metadata.version(name) for name in ("yfinance", "exchange_calendars")
        },
        "limitations": [
            "delayed/revised provider data",
            "no real-time quotes",
            "not a broker execution or paid licensed market-data feed",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    cache_dir.mkdir(parents=True, exist_ok=True)
    latest = cache_dir / "latest.tmp"
    latest.write_text(str(output.resolve()), encoding="utf-8")
    latest.replace(cache_dir / "latest.txt")
    return output
