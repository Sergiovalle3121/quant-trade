"""Offline catalog loading and quote freshness for cloud-rental evaluation.

Quotes, specs, benchmarks, and policy evidence load from YAML/JSON files (or
fixtures in tests). Freshness is recomputed from ``captured_at_utc`` against an
explicit ``evaluated_at_utc`` — a stored staleness number is never trusted, and
an expired or future-dated quote fails closed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from quant_trade.carry.quality import parse_utc
from quant_trade.cloud_rental.models import (
    BenchmarkEvidence,
    CloudProvider,
    ComputeQuote,
    InstanceSpecification,
    ProviderPolicyEvidence,
    PurchaseModel,
    WorkloadPurpose,
)


def _load_payload(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a mapping")
    return payload


def _build(cls: type, raw: dict[str, Any]) -> Any:
    known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
    kwargs = {k: v for k, v in raw.items() if k in known}
    if "provider" in kwargs:
        kwargs["provider"] = CloudProvider(str(kwargs["provider"]))
    if "purchase_model" in kwargs:
        kwargs["purchase_model"] = PurchaseModel(str(kwargs["purchase_model"]))
    if "workload" in kwargs:
        kwargs["workload"] = WorkloadPurpose(str(kwargs["workload"]))
    return cls(**kwargs)


def load_quote(raw: dict[str, Any]) -> ComputeQuote:
    return _build(ComputeQuote, raw)


def load_spec(raw: dict[str, Any]) -> InstanceSpecification:
    return _build(InstanceSpecification, raw)


def load_benchmark(raw: dict[str, Any]) -> BenchmarkEvidence:
    return _build(BenchmarkEvidence, raw)


def load_policy_evidence(raw: dict[str, Any]) -> ProviderPolicyEvidence:
    return _build(ProviderPolicyEvidence, raw)


def load_rental_config(path: str | Path) -> dict[str, Any]:
    """Load an evaluation config: purpose, quote, spec, optional benchmark/policy."""
    payload = _load_payload(path)
    out: dict[str, Any] = {
        "purpose": WorkloadPurpose(str(payload.get("purpose", "control_plane"))),
        "quote": load_quote(payload["quote"]),
        "spec": load_spec(payload["spec"]),
        "benchmark": (
            load_benchmark(payload["benchmark"]) if payload.get("benchmark") else None
        ),
        "policy_evidence": (
            load_policy_evidence(payload["policy_evidence"])
            if payload.get("policy_evidence")
            else None
        ),
        "algorithm": str(payload.get("algorithm", "sha256")),
        "manual_hashrate_declared": bool(
            payload.get("hashrate_hs") or payload.get("manual_hashrate_hs")
        ),
        "revenue": payload.get("revenue", {}),
        "horizon_hours": float(payload.get("horizon_hours", 24.0 * 30)),
        "budget_ceiling_usd": float(payload.get("budget_ceiling_usd", 1000.0)),
    }
    return out


def check_quote_freshness(quote: ComputeQuote, *, evaluated_at_utc: str) -> list[str]:
    """Recomputed freshness problems (empty = fresh). Never trusts stored ages."""
    problems: list[str] = []
    try:
        captured = parse_utc(quote.captured_at_utc)
        now = parse_utc(evaluated_at_utc)
    except ValueError as exc:
        return [f"quote timestamps invalid: {exc}"]
    age_hours = (now - captured).total_seconds() / 3600.0
    if age_hours < 0:
        problems.append("quote is dated in the future")
    elif age_hours > quote.max_age_hours:
        problems.append(
            f"quote captured {age_hours:.1f}h ago exceeds max age {quote.max_age_hours:.0f}h"
        )
    return problems
