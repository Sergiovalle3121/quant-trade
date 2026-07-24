"""Tests for the honest trial ledger: identity, corruption, integrity report."""

from __future__ import annotations

from quant_trade.research.ledger import (
    append_trial,
    append_trial_record,
    build_trial_record,
    compute_hypothesis_id,
    content_fingerprint,
    ledger_integrity_report,
    ledger_path,
    ledger_stats,
    new_attempt_id,
    read_ledger,
    read_trials,
)


def _record(tmp_path, **overrides):
    kwargs = dict(
        source="unit_test",
        strategy="tsmom",
        strategy_params={"lookback_days": 21},
        run_id="run1",
        dataset_sha="datasetA",
        config_sha="cfgA",
        code_sha="codeA",
        seed=7,
        split_policy="chronological:0.7",
        feature_version="v1",
        test_sharpe_per_period=0.05,
    )
    kwargs.update(overrides)
    return build_trial_record(**kwargs)


# --- identity -------------------------------------------------------------


def test_hypothesis_id_is_deterministic_and_param_sensitive():
    a = compute_hypothesis_id("tsmom", {"lookback_days": 21}, "shaX", "split1", "v1")
    b = compute_hypothesis_id("tsmom", {"lookback_days": 21}, "shaX", "split1", "v1")
    c = compute_hypothesis_id("tsmom", {"lookback_days": 42}, "shaX", "split1", "v1")
    d = compute_hypothesis_id("tsmom", {"lookback_days": 21}, "shaY", "split1", "v1")
    assert a == b
    assert a != c  # different params -> new hypothesis
    assert a != d  # different dataset -> new hypothesis
    assert a.startswith("hyp_")


def test_attempt_ids_are_unique():
    ids = {new_attempt_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_fingerprint_distinguishes_rerun_from_new_hypothesis():
    hyp = compute_hypothesis_id("tsmom", {"lookback_days": 21}, "shaX", "split1", "v1")
    same = content_fingerprint(hyp, "code1", "shaX", "cfg1", 7)
    rerun = content_fingerprint(hyp, "code1", "shaX", "cfg1", 7)
    diff_seed = content_fingerprint(hyp, "code1", "shaX", "cfg1", 8)
    assert same == rerun  # identical computation -> reproducible rerun
    assert same != diff_seed  # changed seed -> different content


def test_build_record_populates_identity_fields():
    rec = _record(None)
    assert rec.hypothesis_id.startswith("hyp_")
    assert rec.attempt_id.startswith("att_")
    assert rec.content_fingerprint.startswith("fp_")
    assert rec.status == "evaluated"


# --- write / read round trip ---------------------------------------------


def test_append_record_is_readable_by_legacy_reader(tmp_path):
    append_trial_record(tmp_path, _record(tmp_path))
    trials = read_trials(tmp_path)
    assert len(trials) == 1
    assert trials[0]["source"] == "unit_test"
    assert trials[0]["schema_version"] == 2
    # ledger_stats (legacy API) still works on structured rows
    n, _ = ledger_stats(tmp_path)
    assert n == 1


def test_legacy_flat_rows_remain_supported(tmp_path):
    append_trial(tmp_path, {"source": "old", "test_sharpe_per_period": 0.03})
    append_trial_record(tmp_path, _record(tmp_path))
    report = ledger_integrity_report(tmp_path)
    assert report.legacy_records == 1
    assert report.structured_records == 1
    assert report.valid_records == 2
    assert report.is_intact


# --- corruption is never silent ------------------------------------------


def test_corrupt_lines_are_surfaced_not_dropped(tmp_path):
    append_trial_record(tmp_path, _record(tmp_path))
    with ledger_path(tmp_path).open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
        fh.write("also broken}\n")
    read = read_ledger(tmp_path)
    assert len(read.records) == 1
    assert len(read.corrupt_lines) == 2
    report = ledger_integrity_report(tmp_path)
    assert report.corrupt_lines == 2
    assert report.is_intact is False
    assert report.corrupt_line_numbers  # line numbers recorded
    assert any("corrupt" in note for note in report.notes)


# --- integrity counts -----------------------------------------------------


def test_integrity_counts_hypotheses_attempts_observations(tmp_path):
    # two attempts of the same hypothesis + one different hypothesis
    append_trial_record(tmp_path, _record(tmp_path))
    append_trial_record(tmp_path, _record(tmp_path))  # rerun -> same hypothesis
    append_trial_record(tmp_path, _record(tmp_path, strategy_params={"lookback_days": 63}))
    # a failed and a discarded trial (no usable observation)
    append_trial_record(
        tmp_path, _record(tmp_path, status="failed", test_sharpe_per_period=None, error="boom")
    )
    append_trial_record(
        tmp_path,
        _record(tmp_path, status="discarded", test_sharpe_per_period=None,
                strategy_params={"lookback_days": 999}),
    )
    report = ledger_integrity_report(tmp_path)
    assert report.n_hypotheses == 3
    assert report.n_attempts == 5
    assert report.n_evaluated == 3
    assert report.n_failed == 1
    assert report.n_discarded == 1
    # 3 evaluated rows carry a usable observation; failed/discarded do not
    assert report.n_valid_observations == 3
    assert report.effective_trial_count == 3
    assert "independent" in report.trial_correlation_assumption


def test_reproducible_rerun_groups_detected(tmp_path):
    # identical fingerprint (same code/dataset/config/seed) twice
    append_trial_record(tmp_path, _record(tmp_path))
    append_trial_record(tmp_path, _record(tmp_path))
    report = ledger_integrity_report(tmp_path)
    assert report.reproducible_rerun_groups == 1


def test_missing_ledger_reports_cleanly(tmp_path):
    report = ledger_integrity_report(tmp_path)
    assert report.exists is False
    assert report.valid_records == 0
    assert report.is_intact  # nothing corrupt
