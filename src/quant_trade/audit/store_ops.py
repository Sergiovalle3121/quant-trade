"""Additive private operations and observed commercial costs; no customer payloads."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from typing import Any

OPERATIONS = ("upload", "audit", "pdf", "queue")
OUTCOMES = ("success", "invalid", "busy", "error", "denied")
BUCKETS_MS = (100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000, 120001)
COST_CATEGORIES = ("infrastructure", "payments", "acquisition", "support")


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class OpsStoreMixin:
    """Tables created with the existing Store metadata; old columns never change."""

    _sa: Any
    metadata: Any
    engine: Any
    ops_engine: Any
    ops_counters: Any
    ops_jobs: Any
    commercial_costs: Any

    def define_ops_tables(self) -> None:
        sa = self._sa
        # One bounded, separate PostgreSQL connection: optional metrics cannot
        # exhaust the customer pool or wait indefinitely for a locked counter.
        # SQLite retains the existing engine, including in-memory test databases.
        self.ops_engine = (
            sa.create_engine(
                self.engine.url,
                future=True,
                pool_size=1,
                max_overflow=0,
                pool_timeout=1,
                pool_recycle=300,
                connect_args={
                    "connect_timeout": 2,
                    "options": "-c statement_timeout=2000 -c lock_timeout=500",
                },
            )
            if self.engine.dialect.name == "postgresql"
            else self.engine
        )
        self.ops_counters = sa.Table(
            "ops_counters",
            self.metadata,
            sa.Column("day", sa.String(10), primary_key=True),
            sa.Column("locale", sa.String(8), primary_key=True),
            sa.Column("operation", sa.String(16), primary_key=True),
            sa.Column("outcome", sa.String(16), primary_key=True),
            sa.Column("bucket_ms", sa.Integer, primary_key=True),
            sa.Column("count", sa.Integer, nullable=False),
        )
        self.ops_jobs = sa.Table(
            "ops_jobs",
            self.metadata,
            sa.Column("name", sa.String(32), primary_key=True),
            sa.Column("last_attempt_at", sa.String(40), nullable=False),
            sa.Column("last_success_at", sa.String(40)),
            sa.Column("error_code", sa.String(32), nullable=False),
            sa.Column("deleted_count", sa.Integer, nullable=False),
        )
        self.commercial_costs = sa.Table(
            "commercial_costs",
            self.metadata,
            sa.Column("period_start", sa.String(10), primary_key=True),
            sa.Column("period_end", sa.String(10), primary_key=True),
            sa.Column("scope", sa.String(8), primary_key=True),
            sa.Column("category", sa.String(32), primary_key=True),
            sa.Column("amount_usd_cents", sa.BigInteger, nullable=False),
            sa.Column("source_reference", sa.String(80), nullable=False),
            sa.Column("updated_at", sa.String(40), nullable=False),
        )

    def _ops_insert(self, table: Any) -> Any:
        if self.engine.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        return insert(table)

    def count_ops(
        self,
        *,
        day: str,
        locale: str,
        operation: str,
        outcome: str,
        bucket_ms: int,
        amount: int = 1,
    ) -> None:
        if (
            operation not in OPERATIONS
            or outcome not in OUTCOMES
            or locale not in ("es", "en", "pt")
            or bucket_ms not in BUCKETS_MS
            or amount < 1
        ):
            raise ValueError("invalid operations counter")
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("invalid operations day")
        table = self.ops_counters
        insert = self._ops_insert(table).values(
            day=day,
            locale=locale,
            operation=operation,
            outcome=outcome,
            bucket_ms=bucket_ms,
            count=amount,
        )
        statement = insert.on_conflict_do_update(
            index_elements=[
                table.c.day,
                table.c.locale,
                table.c.operation,
                table.c.outcome,
                table.c.bucket_ms,
            ],
            set_={"count": table.c.count + amount},
        )
        with self.ops_engine.begin() as conn:
            conn.execute(statement)

    def ops_rows(self, since_day: str) -> list[dict[str, Any]]:
        with self.ops_engine.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    self._sa.select(self.ops_counters).where(self.ops_counters.c.day >= since_day)
                ).mappings()
            ]

    def record_ops_job(
        self, *, name: str = "retention", at: datetime, success: bool, deleted_count: int = 0
    ) -> None:
        if name != "retention" or deleted_count < 0:
            raise ValueError("invalid operations job")
        table, timestamp = self.ops_jobs, stamp(at)
        insert = self._ops_insert(table).values(
            name=name,
            last_attempt_at=timestamp,
            last_success_at=timestamp if success else None,
            error_code="" if success else "purge_failed",
            deleted_count=deleted_count,
        )
        # A delayed replica cannot move the latest attempt or success backwards.
        latest = timestamp >= table.c.last_attempt_at
        updates = {
            "last_attempt_at": self._sa.case((latest, timestamp), else_=table.c.last_attempt_at),
            "error_code": self._sa.case(
                (latest, "" if success else "purge_failed"), else_=table.c.error_code
            ),
            "deleted_count": self._sa.case((latest, deleted_count), else_=table.c.deleted_count),
        }
        if success:
            updates["last_success_at"] = self._sa.case(
                (
                    self._sa.or_(
                        table.c.last_success_at.is_(None), timestamp > table.c.last_success_at
                    ),
                    timestamp,
                ),
                else_=table.c.last_success_at,
            )
        with self.ops_engine.begin() as conn:
            conn.execute(insert.on_conflict_do_update(index_elements=[table.c.name], set_=updates))

    def ops_job(self, name: str = "retention") -> dict[str, Any] | None:
        with self.ops_engine.connect() as conn:
            row = (
                conn.execute(self._sa.select(self.ops_jobs).where(self.ops_jobs.c.name == name))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def record_commercial_cost(
        self,
        *,
        period_start: str,
        period_end: str,
        scope: str,
        category: str,
        amount_usd_cents: int,
        source_reference: str,
        at: datetime,
    ) -> None:
        start, end = date.fromisoformat(period_start), date.fromisoformat(period_end)
        if (
            start.isoformat() != period_start
            or end.isoformat() != period_end
            or end < start
            or (end - start).days > 365
            or end > at.astimezone(UTC).date()
            or scope not in ("all", "x")
            or category not in COST_CATEGORIES
            or not 0 <= amount_usd_cents <= 10**12
            or not source_reference
            or len(source_reference) > 80
            or not all(c.isalnum() or c in "-_./ " for c in source_reference)
        ):
            raise ValueError("invalid observed cost")
        table = self.commercial_costs
        insert = self._ops_insert(table).values(
            period_start=period_start,
            period_end=period_end,
            scope=scope,
            category=category,
            amount_usd_cents=amount_usd_cents,
            source_reference=source_reference,
            updated_at=stamp(at),
        )
        with self.ops_engine.begin() as conn:
            conn.execute(
                insert.on_conflict_do_update(
                    index_elements=[
                        table.c.period_start,
                        table.c.period_end,
                        table.c.scope,
                        table.c.category,
                    ],
                    set_={
                        "amount_usd_cents": amount_usd_cents,
                        "source_reference": source_reference,
                        "updated_at": stamp(at),
                    },
                )
            )

    def commercial_cost_rows(
        self, period_start: str, period_end: str, scope: str = "all"
    ) -> list[dict[str, Any]]:
        table = self.commercial_costs
        with self.ops_engine.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    self._sa.select(table).where(
                        (table.c.period_start == period_start)
                        & (table.c.period_end == period_end)
                        & (table.c.scope == scope)
                    )
                ).mappings()
            ]

    def x_cohort_counts(self, since_day: str, until_day: str) -> dict[str, int]:
        """Accounts acquired through X in this window, with events inside it.

        Reuses first-touch attribution; returns aggregates, never customer ids.
        Buyers and repeat purchases count delivered orders, not duplicate charges.
        """
        from datetime import timedelta

        sa = self._sa
        end = (date.fromisoformat(until_day) + timedelta(days=1)).isoformat()
        acc, refs = self.accounts, self.account_refs  # type: ignore[attr-defined]
        source = acc.join(refs, acc.c.id == refs.c.account_id)
        cohort = (
            sa.select(acc.c.id)
            .select_from(source)
            .where(
                (acc.c.created_at >= since_day)
                & (acc.c.created_at < end)
                & ((refs.c.ref == "x") | refs.c.ref.like("x-%"))
            )
        )
        out: dict[str, int] = {}
        with self.ops_engine.connect() as conn:
            out["signups"] = int(
                conn.execute(sa.select(sa.func.count()).select_from(cohort.subquery())).scalar()
                or 0
            )

            def counted(table: Any, account: Any, when: Any, *, extra: Any = None) -> int:
                query = sa.select(sa.func.count(sa.distinct(account))).where(
                    account.in_(cohort), when >= since_day, when < end
                )
                if extra is not None:
                    query = query.where(extra)
                return int(conn.execute(query).scalar() or 0)

            verified = self.verified_emails  # type: ignore[attr-defined]
            out["email_verified"] = counted(
                verified,
                verified.c.account_id,
                verified.c.verified_at,
                extra=verified.c.email
                == sa.select(acc.c.email)
                .where(acc.c.id == verified.c.account_id)
                .scalar_subquery(),
            )
            links = self.account_audits  # type: ignore[attr-defined]
            out["first_upload"] = counted(
                links, links.c.account_id, links.c.linked_at, extra=links.c.via == "upload"
            )
            welcome = self.welcome_reports  # type: ignore[attr-defined]
            out["welcome"] = counted(
                welcome, welcome.c.account_id, welcome.c.created_at, extra=welcome.c.audit_id != ""
            )
            orders = self.checkout_orders  # type: ignore[attr-defined]
            paid = orders.c.status.in_(("delivered", "duplicate", "paid_review"))
            rows = conn.execute(
                sa.select(orders.c.account_id, orders.c.status, orders.c.paid_amount_cents).where(
                    orders.c.account_id.in_(cohort),
                    orders.c.confirmed_at >= since_day,
                    orders.c.confirmed_at < end,
                    orders.c.livemode.is_(True),
                    paid,
                )
            ).all()
            delivered = Counter(str(r[0]) for r in rows if r[1] == "delivered")
            out["buyers"] = len(delivered)
            out["repeat_buyers"] = sum(n > 1 for n in delivered.values())
            out["deliveries"] = sum(delivered.values())
            out["gross_usd_cents"] = sum(int(r[2]) for r in rows)
            refunds = self.stripe_refunds  # type: ignore[attr-defined]
            returned = conn.execute(
                sa.select(sa.func.sum(refunds.c.amount_minor))
                .select_from(refunds.join(orders, refunds.c.order_id == orders.c.id))
                .where(
                    orders.c.account_id.in_(cohort),
                    refunds.c.succeeded_at >= since_day,
                    refunds.c.succeeded_at < end,
                    refunds.c.status == "succeeded",
                    refunds.c.currency == "usd",
                    refunds.c.livemode.is_(True),
                    orders.c.livemode.is_(True),
                )
            ).scalar()
            out["refund_usd_cents"] = int(returned or 0)
        return out
