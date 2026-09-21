"""Parsing: forgiving about names, strict about silent repairs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import business_days, csv_bytes, positive_drift, returns_frame, trades_frame

from quant_trade.audit.schema import (
    MAX_ROWS,
    MAX_UPLOAD_BYTES,
    DeclaredMetadata,
    ParseError,
    build_inputs,
    infer_frequency,
    parse_equity_csv,
    parse_trades_csv,
    parse_variants_csv,
)


def test_equity_aliases_and_utc() -> None:
    frame = positive_drift(50).rename(columns={"timestamp": "Date", "equity": "NAV"})
    frame["Date"] = frame["Date"].dt.strftime("%Y-%m-%d")
    series = parse_equity_csv(csv_bytes(frame))
    assert series.source == "equity"
    assert series.observations == 50
    assert str(series.frame["timestamp"].dt.tz) == "UTC"
    assert series.frame["ret"].iloc[0] != series.frame["ret"].iloc[0]  # NaN first return


def test_semicolon_separator_and_percent_returns() -> None:
    frame = returns_frame(80)
    frame["return"] = [f"{value * 100:.4f}%" for value in frame["return"]]
    series = parse_equity_csv(csv_bytes(frame, sep=";"))
    assert series.source == "returns"
    assert any("percent" in warning for warning in series.warnings)
    assert abs(series.frame["ret"].iloc[1]) < 0.1


def test_percent_heuristic_without_symbol() -> None:
    frame = returns_frame(80)
    frame["return"] = frame["return"] * 100.0
    series = parse_equity_csv(csv_bytes(frame))
    assert any("percentages" in warning for warning in series.warnings)
    assert series.frame["ret"].abs().median() < 0.1


def test_returns_round_trip_keeps_the_first_return() -> None:
    frame = returns_frame(40)
    series = parse_equity_csv(csv_bytes(frame))
    # one base row is prepended, so every uploaded return survives
    assert series.observations == 41
    np.testing.assert_allclose(series.frame["ret"].iloc[1:].to_numpy(), frame["return"])
    np.testing.assert_allclose(
        series.frame["equity"].iloc[1:].to_numpy(), np.cumprod(1 + frame["return"].to_numpy())
    )


def test_duplicates_are_counted_then_dropped_and_order_is_restored() -> None:
    frame = positive_drift(30)
    shuffled = pd.concat([frame.iloc[::-1], frame.iloc[[3]]], ignore_index=True)
    series = parse_equity_csv(csv_bytes(shuffled))
    assert series.duplicate_timestamps == 1
    assert series.non_monotonic is True
    assert series.frame["timestamp"].is_monotonic_increasing
    assert series.observations == 30


def test_unparseable_rows_are_dropped_and_counted() -> None:
    frame = positive_drift(30).astype({"equity": object, "timestamp": object})
    frame.loc[5, "equity"] = "n/a"
    frame.loc[6, "timestamp"] = "not a date"
    series = parse_equity_csv(csv_bytes(frame))
    assert series.unparseable_rows == 2
    assert series.observations == 28


def test_epoch_timestamps_are_understood() -> None:
    frame = positive_drift(30)
    frame["timestamp"] = [int(stamp.timestamp()) for stamp in frame["timestamp"]]
    series = parse_equity_csv(csv_bytes(frame))
    assert series.frame["timestamp"].iloc[0] == business_days(1)[0]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"", "empty"),
        (b"a,b\n1,2\n", "timestamp column"),
        (b"timestamp,foo\n2020-01-01,1\n", "equity column"),
        (b"timestamp,equity\n2020-01-01,1\n", "fewer than two"),
    ],
)
def test_parse_errors_speak_plainly(payload: bytes, message: str) -> None:
    with pytest.raises(ParseError, match=message):
        parse_equity_csv(payload)


def test_size_and_row_limits() -> None:
    with pytest.raises(ParseError, match="bytes"):
        parse_equity_csv(b"x" * (MAX_UPLOAD_BYTES + 1))
    rows = "\n".join(f"2020-01-01,{i}" for i in range(MAX_ROWS + 2))
    with pytest.raises(ParseError, match="rows"):
        parse_equity_csv(f"timestamp,equity\n{rows}\n".encode())


def test_trades_parse_sides_and_client_pnl() -> None:
    frame = trades_frame(10)
    frame.loc[1, "side"] = "sell"
    frame["pnl"] = 5.0
    parsed = parse_trades_csv(csv_bytes(frame))
    assert len(parsed.trades) == 10
    assert parsed.sides[1] == "short"
    assert parsed.client_pnl[0] == 5.0
    assert parsed.invalid_rows == 0
    short = parsed.trades[1]
    assert short.pnl == pytest.approx(-(short.exit_price - short.entry_price) * short.quantity)


def test_trades_invalid_rows_are_dropped() -> None:
    frame = trades_frame(10).astype({"exit_time": object})
    frame.loc[2, "entry_price"] = -1.0
    frame.loc[3, "exit_time"] = "bad"
    frame.loc[4, "side"] = "sideways"
    parsed = parse_trades_csv(csv_bytes(frame))
    assert len(parsed.trades) == 7
    assert parsed.invalid_rows == 3


def test_trades_missing_columns() -> None:
    with pytest.raises(ParseError, match="missing column"):
        parse_trades_csv(b"entry_time,exit_time\n2020-01-01,2020-01-02\n")


def test_variants_matrix() -> None:
    matrix = np.random.default_rng(0).normal(0, 0.01, (64, 4))
    frame = pd.DataFrame(matrix, columns=list("abcd"))
    frame.insert(0, "timestamp", business_days(64))
    parsed = parse_variants_csv(csv_bytes(frame))
    assert parsed.shape == (64, 4)
    with pytest.raises(ParseError, match="two numeric"):
        parse_variants_csv(b"timestamp,a\n2020-01-01,1\n" * 20)


def test_infer_frequency_labels() -> None:
    assert infer_frequency(business_days(300))[1] == "daily_trading"
    assert infer_frequency(pd.date_range("2020-01-01", periods=60, freq="W", tz="UTC"))[1] == (
        "weekly"
    )
    hourly = pd.date_range("2020-01-01", periods=500, freq="h", tz="UTC")
    assert infer_frequency(hourly)[1] == "hourly"


def test_declared_metadata_normalises_oos_start_to_utc() -> None:
    declared = DeclaredMetadata(oos_start="2023-01-01", description="  hola ")
    assert declared.oos_start is not None
    assert declared.oos_start.tzinfo is not None
    assert declared.description == "hola"
    with pytest.raises(ValueError):
        DeclaredMetadata(trials=0)
    with pytest.raises(ValueError):
        DeclaredMetadata(locale="fr")  # type: ignore[arg-type]


def test_build_inputs_hashes_every_file() -> None:
    equity = csv_bytes(positive_drift(120))
    trades = csv_bytes(trades_frame(5))
    inputs = build_inputs(equity, DeclaredMetadata(), trades_bytes=trades)
    assert set(inputs.digests) == {"equity.csv", "trades.csv"}
    assert inputs.frequency_label == "daily_trading"
    assert inputs.trades is not None and len(inputs.trades.trades) == 5
