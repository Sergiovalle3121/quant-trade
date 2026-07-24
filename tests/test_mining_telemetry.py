"""Tests for read-only mining telemetry, alerts, and reconciliation."""

from __future__ import annotations

import pytest

from quant_trade.mining.telemetry import (
    AUTHORIZED_TO_START_MINER,
    HARDWARE_CONTROL_ENABLED,
    WALLET_SIGNING_ENABLED,
    AlertSeverity,
    AlertThresholds,
    DailyOperatingLedger,
    FakeTelemetryAdapter,
    MiningAlert,
    OperatingLedgerEntry,
    RigInventoryItem,
    TelemetryAdapter,
    TelemetrySample,
    evaluate_alerts,
    fleet_report,
    load_samples_from_csv,
    load_samples_from_json,
    reconcile_payouts,
    redact_serial,
    safety_posture,
)


def _inv(**overrides) -> RigInventoryItem:
    base = dict(
        rig_id="rig-1",
        redacted_serial="****ABCD",
        facility="site-a",
        rack="R1",
        algorithm="sha256",
        rated_hashrate_ths=200.0,
        rated_watts=3500.0,
    )
    base.update(overrides)
    return RigInventoryItem(**base)


def _sample(**overrides) -> TelemetrySample:
    base = dict(
        rig_id="rig-1",
        captured_at_utc="2024-05-01T00:00:00Z",
        hashrate_ths=198.0,
        power_watts=3450.0,
        temperature_c=65.0,
        fan_rpm=4200.0,
        reject_rate=0.004,
        uptime_rate=0.98,
        last_seen_utc="2024-05-01T00:00:00Z",
        staleness_seconds=10.0,
    )
    base.update(overrides)
    return TelemetrySample(**base)


def test_safety_flags_are_hardwired_off():
    assert AUTHORIZED_TO_START_MINER is False
    assert HARDWARE_CONTROL_ENABLED is False
    assert WALLET_SIGNING_ENABLED is False
    assert safety_posture() == {
        "authorized_to_start_miner": False,
        "hardware_control_enabled": False,
        "wallet_signing_enabled": False,
    }


def test_adapter_protocol_has_no_control_methods():
    # The read-only contract: only a read() verb, nothing that acts on hardware.
    forbidden = {"start", "stop", "restart", "set_frequency", "overclock", "reboot", "control"}
    assert forbidden.isdisjoint(dir(TelemetryAdapter))


def test_redact_serial_keeps_only_tail():
    assert redact_serial("SN1234567890") == "********7890"
    assert redact_serial("") == ""


def test_fake_adapter_reads_samples():
    adapter = FakeTelemetryAdapter({"rig-1": _sample()})
    assert adapter.read("rig-1").rig_id == "rig-1"
    with pytest.raises(ValueError, match="no telemetry"):
        adapter.read("rig-2")


def test_healthy_sample_has_no_alerts():
    assert evaluate_alerts(_sample(), _inv(), AlertThresholds(), net_daily_profit_usd=5.0) == []


def test_over_temperature_and_hashrate_and_reject_alerts():
    sample = _sample(temperature_c=95.0, hashrate_ths=100.0, reject_rate=0.10)
    alerts = evaluate_alerts(sample, _inv(), AlertThresholds())
    codes = {a.code for a in alerts}
    assert {"over_temperature", "hashrate_drop", "reject_rate_spike"} <= codes


def test_negative_economics_and_payout_mismatch_alerts():
    alerts = evaluate_alerts(
        _sample(), _inv(), AlertThresholds(), net_daily_profit_usd=-3.0, payout_mismatch=True
    )
    codes = {a.code for a in alerts}
    assert "negative_economics" in codes
    assert "payout_mismatch" in codes


def test_stale_telemetry_alert():
    alerts = evaluate_alerts(_sample(staleness_seconds=99999.0), _inv(), AlertThresholds())
    assert any(a.code == "stale_telemetry" for a in alerts)


def test_reconcile_within_and_outside_tolerance():
    ok = reconcile_payouts(1.0, 0.98, tolerance=0.05)
    assert ok.within_tolerance and ok.wallet_is_watch_only
    bad = reconcile_payouts(1.0, 0.5, tolerance=0.05)
    assert not bad.within_tolerance


def test_operating_ledger_totals_and_json(tmp_path):
    ledger = DailyOperatingLedger()
    ledger.add(OperatingLedgerEntry("2024-05-01", "rig-1", 84.0, 6.0, 0.0001, 0.0001, 4.0))
    ledger.add(OperatingLedgerEntry("2024-05-02", "rig-1", 84.0, 6.0, 0.0001, 0.0001, -1.0))
    assert ledger.total_net_usd() == pytest.approx(3.0)
    path = ledger.write_json(tmp_path / "ledger.json")
    assert path.exists()


def test_csv_import(tmp_path):
    csv_path = tmp_path / "telemetry.csv"
    csv_path.write_text(
        "rig_id,captured_at_utc,hashrate_ths,power_watts,temperature_c,fan_rpm,"
        "reject_rate,uptime_rate,last_seen_utc,staleness_seconds\n"
        "rig-1,2024-05-01T00:00:00Z,198,3450,65,4200,0.004,0.98,2024-05-01T00:00:00Z,10\n",
        encoding="utf-8",
    )
    samples = load_samples_from_csv(csv_path)
    assert len(samples) == 1
    assert isinstance(samples[0], TelemetrySample)
    assert samples[0].hashrate_ths == 198.0


def test_alert_serializes():
    a = MiningAlert("x", AlertSeverity.INFO, "m")
    assert a.to_dict()["severity"] == "INFO"


def test_json_import(tmp_path):
    import json

    path = tmp_path / "telemetry.json"
    path.write_text(json.dumps({"samples": [_sample().to_dict()]}), encoding="utf-8")
    samples = load_samples_from_json(path)
    assert len(samples) == 1
    assert samples[0].rig_id == "rig-1"


def test_fleet_report_rolls_up_by_facility_and_flags_alerts():
    inv = [
        _inv(rig_id="rig-1", facility="site-a"),
        _inv(rig_id="rig-2", facility="site-a"),
        _inv(rig_id="rig-3", facility="site-b"),
    ]
    samples = {
        "rig-1": _sample(rig_id="rig-1"),
        "rig-2": _sample(rig_id="rig-2", temperature_c=95.0),  # over-temp
        "rig-3": _sample(rig_id="rig-3"),
    }
    report = fleet_report(inv, samples, AlertThresholds(), net_daily_by_rig={"rig-3": -2.0})
    # safety posture is always off
    assert report.safety == {
        "authorized_to_start_miner": False,
        "hardware_control_enabled": False,
        "wallet_signing_enabled": False,
    }
    facilities = {f.facility: f for f in report.facilities}
    assert facilities["site-a"].rig_count == 2
    assert facilities["site-b"].rig_count == 1
    # rig-2 over-temp + rig-3 negative economics -> at least 2 alerts
    assert report.total_alerts >= 2
    assert any(a["code"] == "over_temperature" for a in report.rig_alerts["rig-2"])
    assert any(a["code"] == "negative_economics" for a in report.rig_alerts["rig-3"])


def test_fleet_report_serializes():
    inv = [_inv()]
    report = fleet_report(inv, {"rig-1": _sample()}, AlertThresholds())
    d = report.to_dict()
    assert "facilities" in d and "safety" in d
