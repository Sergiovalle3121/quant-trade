"""Regression tests for the three confirmed V8 P0 defects.

Each test was written against the V8 behaviour first and observed to fail, so
it pins a real hole rather than describing the fix.

- **A — canary fail-open.** V8 returned `READY_PENDING_HUMAN_AUTHORISATION`
  for a session with `reconciled=false`, an engaged kill switch, and loss
  limits of `{per_trade: -1, daily: 0, total: "bad"}`.
- **B — arbitrary paper P&L.** V8 moved equity from a `paper_fill` that
  referenced no order and carried no price, quantity, side or fee.
- **C — candidate disconnected from paper.** V8 could report
  `NOT_STARTED_NO_CANDIDATE` while a passing campaign existed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_trade.v9.canary import (
    evaluate_canary_readiness_v9,
    validate_loss_limits,
    validate_paper_session,
    validate_reconciliation,
)
from quant_trade.v9.candidate_bridge import (
    STATUS_CANDIDATE_READY,
    STATUS_NO_CANDIDATE,
    bridge_candidate_to_paper,
)
from quant_trade.v9.paper_engine import MarketTick, PaperEngineError
from quant_trade.v9.paper_session import PaperSession, SessionConfig

HOUR_MS = 3_600_000
BASE_MS = 1_700_000_000_000


# --- Defect A: canary fail-open ---------------------------------------------------


def _v8_defect_a_inputs() -> dict:
    """The exact input combination V8 passed."""
    return {
        "evaluated_at_utc": "2026-07-28T00:00:00Z",
        "paper_status": {
            "status": "PAPER_RUNNING",
            "wall_clock_seconds": 72 * 3600,
            "events_processed": 500,
            "clock_is_persisted": True,
            "kill_switch_engaged": True,
            "reconciliation": {"reconciled": False},
        },
        "owner_budget_usd": 500.0,
        "exchange_and_jurisdiction_confirmed": True,
        "loss_limits_configured": {"per_trade": -1, "daily": 0, "total": "bad"},
        "credentials_delivery_mechanism_confirmed": True,
    }


def test_defect_a_canary_blocks_and_enumerates_every_problem() -> None:
    readiness = evaluate_canary_readiness_v9(**_v8_defect_a_inputs())
    assert readiness.status == "BLOCKED"
    assert not readiness.unblocked
    assert "paper_result_sufficient" in readiness.blocking_conditions
    assert "reconciliation_clean" in readiness.blocking_conditions
    assert "loss_limits_configured" in readiness.blocking_conditions
    joined = " | ".join(readiness.all_problems)
    assert "kill switch is engaged" in joined
    assert "reconciled=False" in joined
    assert "per_trade" in joined
    assert "daily" in joined
    assert "total" in joined
    assert readiness.to_dict()["canary_authorized"] is False


def test_defect_a_a_reconciliation_without_a_problems_key_is_not_clean() -> None:
    """Absence of a complaint is not evidence of health."""
    assert validate_reconciliation({"reconciled": False}) != []
    assert validate_reconciliation({}) != []
    assert validate_reconciliation(None) != []
    assert validate_reconciliation({"reconciled": "yes"}) != []
    assert validate_reconciliation({"reconciled": True}) == []


def test_defect_a_reconciliation_error_beyond_tolerance_blocks() -> None:
    problems = validate_reconciliation({"reconciled": True, "reconciliation_error": 0.5})
    assert any("exceeds tolerance" in p for p in problems)


@pytest.mark.parametrize(
    "limits",
    [
        {"per_trade": -1, "daily": 0, "total": "bad"},
        {"per_trade": 0, "daily": 10, "total": 100},
        {"per_trade": 1, "daily": 10},
        {"per_trade": 1, "daily": 10, "total": None},
        {"per_trade": 1, "daily": 10, "total": float("nan")},
        {"per_trade": True, "daily": 10, "total": 100},
        "not an object",
    ],
)
def test_defect_a_invalid_loss_limits_are_rejected(limits: object) -> None:
    assert validate_loss_limits(limits) != []


def test_defect_a_inconsistent_limit_ordering_is_rejected() -> None:
    problems = validate_loss_limits({"per_trade": 100.0, "daily": 10.0, "total": 5.0})
    assert any("per_trade" in p and "exceeds daily" in p for p in problems)
    assert any("daily" in p and "exceeds total" in p for p in problems)


def test_defect_a_sane_limits_pass() -> None:
    assert validate_loss_limits({"per_trade": 5.0, "daily": 25.0, "total": 100.0}) == []


def test_defect_a_a_halted_session_never_supports_a_canary() -> None:
    problems = validate_paper_session(
        {
            "status": "PAPER_RUNNING",
            "wall_clock_seconds": 100 * 3600,
            "events_processed": 5000,
            "clock_is_persisted": True,
            "kill_switch_engaged": True,
        }
    )
    assert any("kill switch is engaged" in p for p in problems)


def test_defect_a_injected_clock_never_supports_a_canary() -> None:
    problems = validate_paper_session(
        {
            "status": "PAPER_RUNNING",
            "wall_clock_seconds": 100 * 3600,
            "events_processed": 5000,
            "clock_is_persisted": False,
        }
    )
    assert any("not derived from persisted" in p for p in problems)


def test_defect_a_a_fully_valid_input_does_unblock() -> None:
    """Otherwise the fix would be an unconditional 'no', not a check."""
    readiness = evaluate_canary_readiness_v9(
        evaluated_at_utc="2026-07-28T00:00:00Z",
        paper_status={
            "status": "PAPER_RUNNING",
            "wall_clock_seconds": 72 * 3600,
            "events_processed": 500,
            "clock_is_persisted": True,
            "kill_switch_engaged": False,
            "liquidations": 0,
            "breakers_tripped": [],
            "reconciliation": {"reconciled": True, "reconciliation_error": 0.0},
        },
        owner_budget_usd=500.0,
        exchange_and_jurisdiction_confirmed=True,
        loss_limits_configured={"per_trade": 5.0, "daily": 25.0, "total": 100.0},
        credentials_delivery_mechanism_confirmed=True,
    )
    assert readiness.status == "CANARY_REQUIRES_HUMAN_AUTHORISATION"
    assert readiness.unblocked
    assert readiness.to_dict()["real_money_authorized"] is False


# --- Defect B: arbitrary paper P&L -------------------------------------------------


def _tick(index: int, *, price: float = 64_000.0, funding: float | None = None) -> MarketTick:
    start = BASE_MS + index * HOUR_MS
    return MarketTick(
        venue="bybit",
        instrument="BTCUSDT",
        bar_start_ms=start,
        bar_end_ms=start + HOUR_MS,
        observed_at_ms=start + HOUR_MS,
        spot_bid=price - 1,
        spot_ask=price + 1,
        perp_bid=price + 1,
        perp_ask=price + 3,
        perp_mark=price + 2,
        index=price,
        settled_funding_rate=funding,
        spot_quote_volume=1e9,
        perp_quote_volume=1e9,
    )


def _session(tmp_path: Path, **overrides):
    clock = [1_000.0]
    session = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    config = SessionConfig(
        session_id="s1",
        candidate_id="H1-v1",
        manifest_sha256="a" * 64,
        initial_capital_usd=10_000.0,
        stale_tick_seconds=2 * 3600.0,
        strategy={
            "entry_threshold": 0.00005,
            "trailing_window": 3,
            "target_notional_usd": 2_000.0,
        },
        execution={
            "latency_ms": 0,
            "slippage_bps": 1.0,
            "max_participation": 1.0,
            "spot_fee_bps": 10.0,
            "perp_fee_bps": 5.5,
        },
        **overrides,
    )
    session.start(config)
    return session, clock


def test_defect_b_advance_accepts_market_data_only(tmp_path: Path) -> None:
    """The V8 hole is closed structurally: there is no P&L argument to pass."""
    import inspect

    signature = inspect.signature(PaperSession.advance)
    assert list(signature.parameters) == ["self", "ticks"]


def test_defect_b_a_yield_bearing_event_is_not_accepted(tmp_path: Path) -> None:
    session, _clock = _session(tmp_path)
    with pytest.raises((TypeError, AttributeError, PaperEngineError)):
        session.advance([{"kind": "paper_fill", "cash_yield_daily": 0.5}])  # type: ignore[list-item]


def test_defect_b_a_fill_requires_an_order(tmp_path: Path) -> None:
    """A fill is produced by the broker from an order; none can be injected."""
    session, _clock = _session(tmp_path)
    assert session.broker is not None
    assert session.broker.open_orders == {}
    assert session.broker.match(_tick(0)) == []


def test_defect_b_equity_moves_only_through_priced_fills_and_funding(
    tmp_path: Path,
) -> None:
    session, clock = _session(tmp_path)
    ticks = []
    for index in range(24):
        ticks.append(_tick(index, price=64_000.0, funding=0.0002 if index % 3 == 0 else None))
        clock[0] += 3600.0
    session.advance(ticks)
    report = session.status_report()
    assert report["counters"]["orders_submitted"] > 0
    assert report["counters"]["fills"] > 0
    # Every dollar of change is attributable to a priced component.
    totals = report["ledger"]["totals"]
    assert totals["fees_usd"] > 0
    assert totals["funding_usd"] != 0
    equity = report["equity_usd"]
    positions = report["ledger"]["positions"]
    reconstructed = (
        report["ledger"]["cash_usd"]
        + report["ledger"]["margin_posted_usd"]
        + positions["spot"]["quantity"] * 64_000.0
        + (positions["perp"]["average_price"] - 64_002.0) * -positions["perp"]["quantity"]
    )
    assert equity == pytest.approx(reconstructed, rel=1e-9)


def test_defect_b_reconciliation_recomputes_equity_from_the_journal(
    tmp_path: Path,
) -> None:
    session, clock = _session(tmp_path)
    ticks = []
    for index in range(12):
        ticks.append(_tick(index, funding=0.0002 if index % 3 == 0 else None))
        clock[0] += 3600.0
    session.advance(ticks)
    result = session.reconcile()
    assert result.reconciled
    assert result.reconciliation_error == pytest.approx(0.0, abs=1e-9)
    assert result.events_replayed > 0


def test_defect_b_a_tick_cannot_claim_to_precede_its_own_bar_close() -> None:
    with pytest.raises(PaperEngineError, match="not observable before the bar ends"):
        MarketTick(
            venue="bybit",
            instrument="BTCUSDT",
            bar_start_ms=BASE_MS,
            bar_end_ms=BASE_MS + HOUR_MS,
            observed_at_ms=BASE_MS + 60_000,  # mid-bar
            spot_bid=1.0,
            spot_ask=1.1,
            perp_bid=1.0,
            perp_ask=1.1,
            perp_mark=1.05,
            index=1.0,
        )


# --- Defect C: candidate disconnected from paper -----------------------------------


class _Campaign:
    """Minimal stand-in carrying the fields the bridge reads."""

    def __init__(self, hypothesis_id: str, status: str, net: float = 0.2) -> None:
        self.hypothesis_id = hypothesis_id
        self.status = status
        self.preregistration_hash = "p" * 64
        self.economics = {"net_return": net, "holdout_net_return": net / 2}
        self.capacity = {"available": True, "capacity_notional_usd": 5_000.0}
        self.holdout = {"selected": f"{hypothesis_id}-v1"}
        self.variants_evaluated = [
            {
                "variant_id": f"{hypothesis_id}-v1",
                "parameters": {"entry_threshold": 5e-5, "trailing_window": 3},
            }
        ]
        self.cost_stack = {
            "bundle_sha256": "c" * 64,
            "components": [
                {"name": "spot_taker_fee", "value": 10.0},
                {"name": "perp_taker_fee", "value": 5.5},
                {"name": "slippage", "value": 1.0},
            ],
        }
        self.evidence = {"venues": {"bybit": {"sufficiency": {"evidence_sha256": "d" * 64}}}}


def test_defect_c_a_candidate_is_never_reported_as_no_candidate(tmp_path: Path) -> None:
    result = bridge_candidate_to_paper(
        [
            _Campaign("H1", "BACKTEST_CANDIDATE", net=0.2),
            _Campaign("H2", "MEASURED_REJECTED", net=-0.1),
            _Campaign("H3", "NOT_MEASURED", net=0.0),
        ],
        created_at_utc="2026-07-28T00:00:00Z",
        state_dir=tmp_path / "session",
    )
    assert result.status == STATUS_CANDIDATE_READY
    assert result.status != STATUS_NO_CANDIDATE
    assert result.has_candidate
    assert result.candidate_id == "H1-H1-v1"
    assert result.manifest["manifest_sha256"]
    assert result.start_command.startswith("quant-trade v9 paper-start")


def test_defect_c_no_candidate_says_so_and_explains_why(tmp_path: Path) -> None:
    result = bridge_candidate_to_paper(
        [
            _Campaign("H1", "MEASURED_REJECTED"),
            _Campaign("H2", "NOT_MEASURED"),
        ],
        created_at_utc="2026-07-28T00:00:00Z",
        state_dir=tmp_path / "session",
    )
    assert result.status == STATUS_NO_CANDIDATE
    assert not result.has_candidate
    assert "H1=MEASURED_REJECTED" in result.reason


def test_defect_c_the_manifest_actually_starts_a_session(tmp_path: Path) -> None:
    """The bridge's output must be runnable, not merely well-formed."""
    from quant_trade.v9.candidate_bridge import build_manifest_from_campaign

    manifest = build_manifest_from_campaign(
        _Campaign("H1", "BACKTEST_CANDIDATE"),
        created_at_utc="2026-07-28T00:00:00Z",
        capital_usd=10_000.0,
    )
    clock = [1_000.0]
    session = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    session.start(manifest.session_config("s1"))
    ticks = []
    for index in range(12):
        ticks.append(_tick(index, funding=0.0002 if index % 3 == 0 else None))
        clock[0] += 3600.0
    session.advance(ticks)
    report = session.status_report()
    assert report["candidate_id"] == manifest.candidate_id
    assert report["manifest_sha256"] == manifest.manifest_sha256
    assert report["counters"]["ticks_applied"] == 12


def test_defect_c_the_best_candidate_is_selected_when_several_pass(
    tmp_path: Path,
) -> None:
    result = bridge_candidate_to_paper(
        [
            _Campaign("H1", "BACKTEST_CANDIDATE", net=0.05),
            _Campaign("H2", "BACKTEST_CANDIDATE", net=0.30),
        ],
        created_at_utc="2026-07-28T00:00:00Z",
        state_dir=tmp_path / "session",
    )
    assert result.candidate_id.startswith("H2")
