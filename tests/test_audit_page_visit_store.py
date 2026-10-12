"""Page visits remain anonymous aggregates with an additive, atomic schema."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

sa = pytest.importorskip("sqlalchemy")

from quant_trade.audit.store import Store, make_store  # noqa: E402

DAY = "2026-10-11"


@pytest.fixture
def store(tmp_path: Path):
    instance = make_store(f"sqlite:///{tmp_path}/visits.db")
    yield instance
    instance.engine.dispose()


def test_page_visit_schema_contains_only_aggregate_dimensions(store: Store) -> None:
    table = store.funnel_page_visits
    assert set(table.c.keys()) == {"day", "locale", "ref", "page_group", "visits"}
    assert set(table.primary_key.columns.keys()) == {"day", "locale", "ref", "page_group"}
    assert table.c.page_group.type.length == 96
    assert set(store.funnel_visits.c.keys()) == {"day", "locale", "ref", "visits"}


def test_legacy_schema_adds_page_table_without_inventing_historical_groups(
    tmp_path: Path,
) -> None:
    url = f"sqlite:///{tmp_path}/legacy.db"
    engine = sa.create_engine(url)
    metadata = sa.MetaData()
    legacy = sa.Table(
        "funnel_visits",
        metadata,
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("locale", sa.String(8), primary_key=True),
        sa.Column("ref", sa.String(24), primary_key=True),
        sa.Column("visits", sa.Integer, nullable=False, default=0),
    )
    with engine.begin() as conn:
        metadata.create_all(conn)
        conn.execute(legacy.insert().values(day=DAY, locale="es", ref="f6", visits=9))
    engine.dispose()
    upgraded = make_store(url)
    try:
        assert upgraded.funnel_events(DAY)["visits"] == [(DAY, "es", "f6", 9)]
        assert upgraded.page_visit_rows(DAY) == []
        upgraded.count_visit(day=DAY, locale="es", ref="f6", page_group="landing", amount=2)
        upgraded.count_visit(day=DAY, locale="es", ref="f6")
        assert upgraded.funnel_events(DAY)["visits"] == [(DAY, "es", "f6", 12)]
        assert upgraded.page_visit_rows(DAY) == [(DAY, "es", "f6", "landing", 2)]
    finally:
        upgraded.engine.dispose()


def test_page_counts_keep_dimensions_and_return_sorted_rows_since_day(store: Store) -> None:
    rows = [
        (DAY, "es", "f6", "landing", 2),
        (DAY, "es", "f6", "calculadora-reto/ftmo", 3),
        (DAY, "en", "f6", "landing", 4),
        (DAY, "es", "", "v/publicacion", 5),
        ("2026-10-10", "es", "f6", "lectura", 6),
    ]
    for day, locale, ref, group, count in rows:
        store.count_visit(day=day, locale=locale, ref=ref, page_group=group, amount=count)
    store.count_visit(day=DAY, locale="es", ref="f6", page_group="landing", amount=7)
    expected = [(DAY, "es", "f6", "landing", 9), *rows[1:4]]
    assert store.page_visit_rows(DAY) == sorted(expected)
    assert sorted(store.funnel_events(DAY)["visits"]) == [
        (DAY, "en", "f6", 4),
        (DAY, "es", "", 5),
        (DAY, "es", "f6", 12),
    ]


@pytest.mark.parametrize(
    "page_group",
    [
        "landing?token=private",
        "v/client-report-id",
        "v/ejemplo?ref=f6",
        "https://example.test/lectura",
        "guias/private-report-id",
        "LANDING",
        "x" * 200,
    ],
)
def test_private_or_unknown_page_groups_are_rejected_before_counting(
    store: Store, page_group: str
) -> None:
    with pytest.raises(ValueError, match="invalid visit page group"):
        store.count_visit(day=DAY, locale="es", ref="f6", page_group=page_group)
    assert store.funnel_events(DAY)["visits"] == []
    assert store.page_visit_rows(DAY) == []


@pytest.mark.parametrize("existing", [False, True])
def test_failed_page_write_rolls_back_both_counts_before_retry(
    store: Store, existing: bool
) -> None:
    if existing:
        store.count_visit(day=DAY, locale="es", ref="f6", page_group="landing", amount=2)

    def fail_page_write(
        _conn: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: Any
    ) -> None:
        if statement.startswith("INSERT INTO funnel_page_visits"):
            raise RuntimeError("synthetic page counter failure")

    sa.event.listen(store.engine, "before_cursor_execute", fail_page_write)
    try:
        with pytest.raises(RuntimeError, match="synthetic page counter failure"):
            store.count_visit(day=DAY, locale="es", ref="f6", page_group="landing", amount=3)
    finally:
        sa.event.remove(store.engine, "before_cursor_execute", fail_page_write)
    assert store.funnel_events(DAY)["visits"] == ([(DAY, "es", "f6", 2)] if existing else [])
    assert store.page_visit_rows(DAY) == ([(DAY, "es", "f6", "landing", 2)] if existing else [])
    store.count_visit(day=DAY, locale="es", ref="f6", page_group="landing", amount=3)
    expected = 5 if existing else 3
    assert store.funnel_events(DAY)["visits"] == [(DAY, "es", "f6", expected)]
    assert store.page_visit_rows(DAY) == [(DAY, "es", "f6", "landing", expected)]


def test_concurrent_page_visits_preserve_original_and_group_totals(store: Store) -> None:
    workers = 6
    ready = threading.Barrier(workers)

    def count(index: int) -> None:
        group = "landing" if index % 2 else "lectura"
        ready.wait(timeout=10)
        for _ in range(20):
            store.count_visit(day=DAY, locale="es", ref="f6", page_group=group)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(count, range(workers)))
    assert store.funnel_events(DAY)["visits"] == [(DAY, "es", "f6", workers * 20)]
    assert store.page_visit_rows(DAY) == [
        (DAY, "es", "f6", "landing", workers * 10),
        (DAY, "es", "f6", "lectura", workers * 10),
    ]
