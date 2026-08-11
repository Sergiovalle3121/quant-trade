"""Tests for the durable holdout seal: binding to bytes, refusing rewrites,
refusing overlap, guarding research dates, and revealing exactly once."""

from __future__ import annotations

import pytest

from quant_trade.research.holdout_seal import (
    SEAL_FILENAME,
    HoldoutSeal,
    HoldoutSealError,
    assert_not_revealed,
    assert_within_selection,
    dataset_digest,
    load_seal,
    read_reveals,
    record_reveal,
    seal_holdout,
    verify_against_dataset,
)

COMPONENTS = {"2020-01-01": "a" * 64, "2020-01-02": "b" * 64}


def _seal(**overrides) -> HoldoutSeal:
    kwargs = dict(
        seal_id="crypto_lowcap_v1",
        dataset_id="crypto_lowcap_universe_v1",
        dataset_digest=dataset_digest(COMPONENTS),
        selection_start="2017-08-17",
        selection_end="2023-11-30",
        holdout_start="2023-12-01",
        holdout_end="2026-08-09",
        rationale="final 30% reserved; regime asymmetry declared",
        sealed_at_utc="2026-08-11T06:00:00Z",
    )
    kwargs.update(overrides)
    return HoldoutSeal(**kwargs)  # type: ignore[arg-type]


def test_digest_changes_when_any_member_changes() -> None:
    base = dataset_digest(COMPONENTS)
    assert dataset_digest({**COMPONENTS, "2020-01-02": "c" * 64}) != base
    assert dataset_digest({**COMPONENTS, "2020-01-03": "d" * 64}) != base
    assert dataset_digest({"2020-01-01": "a" * 64}) != base
    assert dataset_digest(dict(reversed(list(COMPONENTS.items())))) == base


def test_empty_dataset_cannot_be_sealed() -> None:
    with pytest.raises(HoldoutSealError, match="constrains nothing"):
        dataset_digest({})


def test_overlapping_sections_are_not_a_holdout() -> None:
    with pytest.raises(HoldoutSealError, match="overlapping"):
        _seal(holdout_start="2023-11-30")


def test_rationale_is_required() -> None:
    with pytest.raises(HoldoutSealError, match="rationale"):
        _seal(rationale="   ")


def test_seal_is_stable_and_excludes_metadata() -> None:
    assert _seal().seal() == _seal().seal()
    assert _seal(notes=["anything"]).seal() == _seal().seal()
    assert _seal(rationale="different").seal() != _seal().seal()


def test_a_sealed_holdout_is_never_rewritten(tmp_path) -> None:
    seal_holdout(tmp_path, _seal())
    with pytest.raises(HoldoutSealError, match="never rewritten"):
        seal_holdout(tmp_path, _seal(holdout_start="2024-01-01"))


def test_editing_the_file_breaks_the_seal(tmp_path) -> None:
    import json

    seal_holdout(tmp_path, _seal())
    path = tmp_path / SEAL_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["holdout_start"] = "2025-01-01"  # move the boundary after the fact
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HoldoutSealError, match="edited after sealing"):
        load_seal(tmp_path)


def test_a_changed_dataset_fails_closed(tmp_path) -> None:
    seal_holdout(tmp_path, _seal())
    loaded = load_seal(tmp_path)
    verify_against_dataset(loaded, COMPONENTS)  # unchanged: fine
    with pytest.raises(HoldoutSealError, match="changed after sealing"):
        verify_against_dataset(loaded, {**COMPONENTS, "2020-01-03": "e" * 64})


def test_research_dates_reaching_into_the_holdout_raise() -> None:
    seal = _seal()
    assert_within_selection(seal, ["2017-08-17", "2020-06-01", "2023-11-30"])
    with pytest.raises(HoldoutSealError, match="outside the selection window"):
        assert_within_selection(seal, ["2023-11-30", "2023-12-01"])


def test_reveal_happens_once_and_names_what_it_judges(tmp_path) -> None:
    seal_holdout(tmp_path, _seal())
    assert_not_revealed(tmp_path)
    record = record_reveal(
        tmp_path,
        reason="final evaluation of the single selected candidate",
        at_utc="2026-08-11T07:00:00Z",
        frozen_selection={"strategy": "xs_momentum", "trial_id": "t7"},
    )
    assert record["frozen_selection"]["trial_id"] == "t7"
    assert len(read_reveals(tmp_path)) == 1
    with pytest.raises(HoldoutSealError, match="already revealed"):
        assert_not_revealed(tmp_path)
    with pytest.raises(HoldoutSealError, match="already revealed"):
        record_reveal(
            tmp_path,
            reason="just one more look",
            at_utc="2026-08-11T08:00:00Z",
            frozen_selection={"strategy": "other"},
        )


def test_a_reveal_that_cannot_say_what_it_tests_is_refused(tmp_path) -> None:
    seal_holdout(tmp_path, _seal())
    with pytest.raises(HoldoutSealError, match="already-frozen selection"):
        record_reveal(
            tmp_path,
            reason="curiosity",
            at_utc="2026-08-11T07:00:00Z",
            frozen_selection={},
        )
    assert read_reveals(tmp_path) == []  # a refused reveal leaves no trace of use


def test_reveal_requires_a_seal_to_exist(tmp_path) -> None:
    with pytest.raises(HoldoutSealError, match="no sealed holdout"):
        record_reveal(
            tmp_path,
            reason="x",
            at_utc="2026-08-11T07:00:00Z",
            frozen_selection={"strategy": "y"},
        )
