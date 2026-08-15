from __future__ import annotations

import calendar as month_calendar
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml

from quant_trade.research.prospective_spy_tom import (
    STRATEGY_ID,
    ExchangeSession,
    ExplicitExchangeCalendar,
    SpyTomError,
    SpyTomSpec,
    TargetIntention,
    generate_spy_tom_targets,
    load_spy_tom_spec,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "experiments" / "spy_tom_dm1_p3_v1.yaml"
NY = ZoneInfo("America/New_York")


def _spec() -> SpyTomSpec:
    return load_spy_tom_spec(CONFIG)


def _month_sessions(year: int, month: int, closed: set[date]) -> list[date]:
    return [
        day
        for number in range(1, month_calendar.monthrange(year, month)[1] + 1)
        if (day := date(year, month, number)).weekday() < 5 and day not in closed
    ]


def _calendar(
    first: tuple[int, int, set[date]],
    second: tuple[int, int, set[date]],
) -> ExplicitExchangeCalendar:
    first_year, first_month, first_closed = first
    second_year, second_month, second_closed = second
    session_dates = _month_sessions(first_year, first_month, first_closed)
    session_dates.extend(_month_sessions(second_year, second_month, second_closed))
    return ExplicitExchangeCalendar(
        calendar_id="XNYS",
        complete_months=(
            f"{first_year:04d}-{first_month:02d}",
            f"{second_year:04d}-{second_month:02d}",
        ),
        sessions=tuple(_session(day) for day in session_dates),
    )


def _holiday_calendar() -> ExplicitExchangeCalendar:
    return _calendar(
        (2025, 12, {date(2025, 12, 25)}),
        (2026, 1, {date(2026, 1, 1), date(2026, 1, 19)}),
    )


def _at(day: date, *, tz: Any = NY, hour: int = 15, minute: int = 55) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def _session(day: date, *, close_hour: int = 16) -> ExchangeSession:
    return ExchangeSession(
        session_date=day,
        open_timestamp=_at(day, hour=9, minute=30),
        close_timestamp=_at(day, hour=close_hour, minute=0),
    )


def test_yaml_is_exact_deeply_immutable_and_canonically_sealed() -> None:
    spec = _spec()

    assert spec.strategy_id == STRATEGY_ID
    assert spec.seal() == "5d2c57f22a4437b3064a596b3dd804c7e1e683b3228d4a5d6901e73f1053c540"
    assert spec.capital_policy["paper_starting_capital_cents"] == 20_000
    assert spec.capital_policy["maximum_gross_exposure_cents"] == 19_500
    assert spec.capital_policy["minimum_cash_reserve_cents"] == 500
    assert spec.sample_policy["minimum_paired_months"] == 120
    assert spec.sample_policy["all_historical_data_classification"] == "DEVELOPMENT_ONLY"
    assert spec.return_accounting["total_return_required"] is True
    assert spec.return_accounting["price_return_only_allowed"] is False
    assert spec.verdict_policy["pass_verdict_allowed"] is False
    assert spec.verdict_policy["maximum_verdict"] == "INSUFFICIENT_EVIDENCE"
    assert spec.authorization["paper_order_routing_enabled"] is False
    assert spec.authorization["live_execution_enabled"] is False
    assert spec.authorization["real_money_authorized"] is False

    with pytest.raises(TypeError):
        spec.capital_policy["maximum_gross_exposure_cents"] = 20_000  # type: ignore[index]
    with pytest.raises(TypeError):
        spec.instrument_policy["allowed_symbols"][0] = "QQQ"  # type: ignore[index]


def test_yaml_tamper_and_resealed_policy_change_both_fail_closed(tmp_path: Path) -> None:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw["seal"] = "f" * 64
    path = tmp_path / "tampered.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(SpyTomError, match="seal mismatch"):
        load_spy_tom_spec(path)

    policy = dict(_spec().authorization)
    policy["live_execution_enabled"] = True
    with pytest.raises(SpyTomError, match="sealed SPY TOM campaign"):
        replace(_spec(), authorization=policy)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("symbol", "QQQ"),
        ("trial_budget", 2),
        ("campaign_mode", "LIVE"),
    ],
)
def test_constructor_rejects_resealed_scalar_changes(field: str, value: Any) -> None:
    payload = _spec().canonical_payload()
    payload[field] = value
    with pytest.raises(SpyTomError, match="sealed SPY TOM campaign"):
        SpyTomSpec(**payload)


def test_generator_revalidates_and_rejects_post_constructor_forgery() -> None:
    forged = _spec()
    object.__setattr__(forged, "symbol", "QQQ")

    with pytest.raises(SpyTomError, match="forged or invalid"):
        generate_spy_tom_targets(
            forged,
            _holiday_calendar(),
            (),
            as_of=_at(date(2026, 1, 31)),
        )


def test_exact_holiday_schedule_emits_primary_and_paired_control_windows() -> None:
    observations = (
        _at(date(2025, 12, 30)),
        _at(date(2026, 1, 6)),
        _at(date(2026, 1, 13)),
        _at(date(2026, 1, 20)),
    )

    targets = generate_spy_tom_targets(
        _spec(),
        _holiday_calendar(),
        observations,
        as_of=_at(date(2026, 1, 20), hour=16),
    )

    assert [(target.leg, target.action) for target in targets] == [
        ("PRIMARY", "ENTRY"),
        ("PRIMARY", "EXIT"),
        ("CONTROL", "ENTRY"),
        ("CONTROL", "EXIT"),
    ]
    assert [target.decision_timestamp.date() for target in targets] == [
        date(2025, 12, 30),  # Penultimate session; December 31 is the last session.
        date(2026, 1, 6),  # Third session; New Year's Day is not a session.
        date(2026, 1, 13),  # Eighth session.
        date(2026, 1, 20),  # Twelfth session; MLK Day is not a session.
    ]
    assert [target.target_exposure_cents for target in targets] == [19_500, 0, 19_500, 0]
    assert {target.pair_id for target in targets} == {"2025-12_TO_2026-01"}
    assert {target.symbol for target in targets} == {"SPY"}
    assert {target.order_intent for target in targets} == {"RESEARCH_TARGET_ONLY"}
    assert {target.verdict_ceiling for target in targets} == {"INSUFFICIENT_EVIDENCE"}
    assert not any(target.real_money_authorized for target in targets)


def test_t_plus_one_expiry_and_capital_reserve_are_explicit() -> None:
    decision = _at(date(2025, 12, 30))
    target = generate_spy_tom_targets(
        _spec(),
        _holiday_calendar(),
        (decision,),
        as_of=decision,
    )[0]

    assert target.decision_timestamp.hour == 15
    assert target.decision_timestamp.minute == 55
    assert target.earliest_execution_timestamp > target.decision_timestamp
    assert target.earliest_execution_timestamp.hour == 15
    assert target.earliest_execution_timestamp.minute == 56
    assert target.expires_at.hour == 15
    assert target.expires_at.minute == 58
    assert target.earliest_execution_timestamp < target.expires_at
    assert target.maximum_gross_exposure_cents == 19_500
    assert target.minimum_cash_reserve_cents == 500
    assert target.fractional_shares_required is True


def test_target_constructor_is_generator_only_and_rejects_direct_date_forgery() -> None:
    decision = _at(date(2025, 12, 30))
    valid: dict[str, Any] = {
        "strategy_id": STRATEGY_ID,
        "strategy_spec_seal": _spec().seal(),
        "pair_id": "2025-12_TO_2026-01",
        "leg": "PRIMARY",
        "action": "ENTRY",
        "symbol": "SPY",
        "decision_timestamp": decision,
        "earliest_execution_timestamp": decision + timedelta(minutes=1),
        "expires_at": decision + timedelta(minutes=3),
        "target_exposure_cents": 19_500,
        "maximum_gross_exposure_cents": 19_500,
        "minimum_cash_reserve_cents": 500,
        "fractional_shares_required": True,
        "order_intent": "RESEARCH_TARGET_ONLY",
        "verdict_ceiling": "INSUFFICIENT_EVIDENCE",
        "real_money_authorized": False,
    }

    with pytest.raises(SpyTomError, match="only be constructed"):
        TargetIntention(**valid)

    forged_date = _at(date(2026, 1, 7))
    valid.update(
        {
            "decision_timestamp": forged_date,
            "earliest_execution_timestamp": forged_date + timedelta(minutes=1),
            "expires_at": forged_date + timedelta(minutes=3),
            "action": "EXIT",
            "target_exposure_cents": 0,
        }
    )
    with pytest.raises(SpyTomError, match="only be constructed"):
        TargetIntention(**valid)


def test_targets_are_prefix_invariant_when_future_observations_are_appended() -> None:
    calendar = _holiday_calendar()
    prefix_observations = (
        _at(date(2025, 12, 30)),
        _at(date(2026, 1, 6)),
    )
    future_observations = prefix_observations + (
        _at(date(2026, 1, 13)),
        _at(date(2026, 1, 20)),
    )
    cutoff = prefix_observations[-1]

    before = generate_spy_tom_targets(
        _spec(),
        calendar,
        prefix_observations,
        as_of=cutoff,
    )
    after = generate_spy_tom_targets(
        _spec(),
        calendar,
        future_observations,
        as_of=future_observations[-1],
    )

    assert before == tuple(target for target in after if target.decision_timestamp <= cutoff)


def test_dst_is_derived_from_new_york_zone_not_a_fixed_offset() -> None:
    calendar = _calendar(
        (2026, 2, {date(2026, 2, 16)}),
        (2026, 3, set()),
    )
    observations = (
        _at(date(2026, 2, 26)),
        _at(date(2026, 3, 4)),
        _at(date(2026, 3, 11)),
        _at(date(2026, 3, 17)),
    )

    targets = generate_spy_tom_targets(
        _spec(),
        calendar,
        observations,
        as_of=_at(date(2026, 3, 17), hour=16),
    )

    assert targets[0].decision_timestamp.utcoffset().total_seconds() == -5 * 3600
    assert targets[1].decision_timestamp.utcoffset().total_seconds() == -5 * 3600
    assert targets[2].decision_timestamp.utcoffset().total_seconds() == -4 * 3600
    assert targets[3].decision_timestamp.utcoffset().total_seconds() == -4 * 3600


def test_missing_exact_bar_emits_no_fallback_to_nearby_session() -> None:
    observations = (
        _at(date(2025, 12, 29)),  # Valid session, but not the sealed entry session.
        _at(date(2026, 1, 6)),
        _at(date(2026, 1, 13)),
        _at(date(2026, 1, 20)),
    )

    targets = generate_spy_tom_targets(
        _spec(),
        _holiday_calendar(),
        observations,
        as_of=_at(date(2026, 1, 20), hour=16),
    )

    assert not any(target.leg == "PRIMARY" and target.action == "ENTRY" for target in targets)
    assert date(2025, 12, 29) not in {target.decision_timestamp.date() for target in targets}


def test_early_close_on_any_required_session_excludes_entire_pair() -> None:
    june_dates = _month_sessions(2025, 6, {date(2025, 6, 19)})
    july_dates = _month_sessions(2025, 7, {date(2025, 7, 4)})
    sessions = [_session(day) for day in june_dates]
    sessions.extend(
        _session(day, close_hour=13) if day == date(2025, 7, 3) else _session(day)
        for day in july_dates
    )
    calendar = ExplicitExchangeCalendar(
        "XNYS",
        ("2025-06", "2025-07"),
        sessions,
    )
    observations = tuple(_at(day) for day in calendar.session_dates)

    targets = generate_spy_tom_targets(
        _spec(),
        calendar,
        observations,
        as_of=_at(date(2025, 7, 31), hour=16),
    )

    assert targets == ()


@pytest.mark.parametrize(
    "observations",
    [
        (datetime(2025, 12, 30, 15, 55),),
        (_at(date(2025, 12, 30), hour=15, minute=54),),
        (_at(date(2026, 1, 13), tz=UTC),),
    ],
)
def test_naive_wrong_minute_and_wrong_timezone_observations_fail(
    observations: tuple[datetime, ...],
) -> None:
    with pytest.raises(SpyTomError, match="timezone-aware|exactly 15:55"):
        generate_spy_tom_targets(
            _spec(),
            _holiday_calendar(),
            observations,
            as_of=_at(date(2026, 1, 31), hour=16),
        )


def test_fixed_standard_offset_cannot_impersonate_new_york_during_dst() -> None:
    calendar = _calendar(
        (2026, 2, {date(2026, 2, 16)}),
        (2026, 3, set()),
    )
    wrong = _at(date(2026, 3, 11), tz=UTC).replace(hour=20, minute=55)
    # 20:55 UTC is 16:55 in New York after the DST transition.
    with pytest.raises(SpyTomError, match="exactly 15:55"):
        generate_spy_tom_targets(
            _spec(),
            calendar,
            (wrong,),
            as_of=wrong,
        )


def test_naive_as_of_future_observation_and_reordered_observations_fail() -> None:
    first = _at(date(2025, 12, 30))
    second = _at(date(2026, 1, 6))
    with pytest.raises(SpyTomError, match="as_of must be"):
        generate_spy_tom_targets(
            _spec(),
            _holiday_calendar(),
            (),
            as_of=datetime(2026, 1, 31, 16),
        )
    with pytest.raises(SpyTomError, match="later than as_of"):
        generate_spy_tom_targets(
            _spec(),
            _holiday_calendar(),
            (second,),
            as_of=first,
        )
    with pytest.raises(SpyTomError, match="strictly increasing"):
        generate_spy_tom_targets(
            _spec(),
            _holiday_calendar(),
            (second, first),
            as_of=second,
        )


def test_malformed_calendars_fail_instead_of_repairing_or_falling_back() -> None:
    december = _month_sessions(2025, 12, {date(2025, 12, 25)})
    january = _month_sessions(2026, 1, {date(2026, 1, 1), date(2026, 1, 19)})

    with pytest.raises(SpyTomError, match="strictly increasing"):
        ExplicitExchangeCalendar(
            "XNYS",
            ("2025-12", "2026-01"),
            [_session(day) for day in december + list(reversed(january))],
        )
    with pytest.raises(SpyTomError, match="Saturdays or Sundays"):
        ExplicitExchangeCalendar(
            "XNYS",
            ("2025-12", "2026-01"),
            [_session(day) for day in sorted(december + [date(2025, 12, 6)] + january)],
        )
    with pytest.raises(SpyTomError, match="adjacent"):
        ExplicitExchangeCalendar(
            "XNYS",
            ("2025-12", "2026-02"),
            [_session(day) for day in december + _month_sessions(2026, 2, {date(2026, 2, 16)})],
        )
    with pytest.raises(SpyTomError, match="at least 12"):
        ExplicitExchangeCalendar(
            "XNYS",
            ("2025-12", "2026-01"),
            [_session(day) for day in december + january[:11]],
        )
