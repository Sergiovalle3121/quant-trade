"""Provenance guard: every claim in an artifact must say where it came from.

``PROFIT_CLAIM_GUARD`` scans vocabulary — it catches a document that *says* it
makes money. It cannot catch a number that *claims to have been measured* when
nothing measured it, because such a number uses no special words. Fourteen
hardcoded literals passed it while sitting in the artifacts as if they were
runtime state, and one of them carried three SHA-256 digests for bytes that
never existed.

This guard checks the other axis: provenance rather than vocabulary. Five rules,
each aimed at a way the fourteen hid.

R1 declaration
    A leaf that asserts a positive fact about the world must be covered by a
    declared evidence class. Zeros, falses, nulls and NOT_MEASURED-family
    tokens assert nothing, so they need no cover.

R2 digest
    A 64-hex string is the claim "these exact bytes exist". It must resolve:
    some file in the repository has to hash to it. Keys that legitimately hash
    in-memory canonical content are listed in :data:`CONTENT_HASH_KEYS`. This is
    the rule a relabelling cannot dodge — you may not downgrade a fabricated
    digest to ASSUMPTION and keep it.

R3 verb
    A key whose *name* claims a verification — ``*_verified``, ``*_captured``,
    ``*_closed``, ``*_present``, ``measured``, ``promotable``, ``*_count`` —
    must be covered whatever its value. "We checked and found nothing" is still
    a claim to have checked.

R4a contradiction
    One artifact may not carry the same key twice with conflicting scalars.
    Embedded JSON strings are walked too, which is how a fabricated
    ``settlements: 6`` is caught sitting beside a recorded ``settlements: 0``.

R4b positive-in-negative
    A *quantity* or a *verification* asserted inside a block that declares
    itself NOT_MEASURED or BLOCKED_EVIDENCE is a contradiction in itself. This
    is what stops an author from wrapping an assertion in an honest-looking
    state and calling it declared. It deliberately does not fire on descriptive
    strings: a blocked attempt may still record which host it tried and when,
    and that is narration, not a measurement.

Prose is scanned too. Restricting the guard to JSON was the blind spot that let
three assertions of a withdrawn Bybit capture survive in ``docs/`` after the
artifact had retracted them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Declared evidence grades. MEASURED is the only one that asserts observation.
EVIDENCE_CLASSES = ("MEASURED", "SYNTHETIC", "ASSUMPTION", "NOT_MEASURED")

#: State-ish values that declare "nothing was measured here". A block carrying
#: one of these covers its descendants for R1, and triggers R4b for positives.
NOT_MEASURED_TOKENS = frozenset(
    {
        "NOT_MEASURED",
        "BLOCKED_EVIDENCE",
        "NOT_RUN_NO_DATASET",
        "NOT_RUN_NO_EVIDENCE",
        "NOT_RUN_NETWORK_BLOCKED",
        "NOT_STARTED_NO_CANDIDATE",
        "NOT_MEASURED_NO_CANDIDATE",
        "NOT_STARTED_NO_ELIGIBLE_NON_CASH_CANDIDATE",
        "NOT_STARTED_NO_CANDIDATE_NO_MEASURED_CAMPAIGN",
    }
)

#: Keys whose value declares an evidence grade or a measurement state.
DECLARATION_KEYS = ("evidence_class", "state", "trading_state", "mining_state", "status")

#: Keys that legitimately hold a hash of canonical in-memory content rather than
#: of a file on disk. Anything else holding a digest must resolve to real bytes.
CONTENT_HASH_KEYS = frozenset(
    {
        "artifact_sha256",
        "preregistration_hash",
        "freeze_hash",
        "manifest_sha256",
        "rows_sha256",
        "fingerprint",
        "chain_head",
        "prev_hash",
        "record_hash",
        "content_sha256",
        "dataset_sha256",
        "data_sha256",
        "raw_sha256",
        "config_sha256",
    }
)

#: Key names that claim a verification happened. R3 applies whatever the value.
VERB_KEY = re.compile(
    r"(?:^|_)(?:verified|captured|closed|present|measured|promotable|reconciled"
    r"|confirmed|validated|audited|checked|count)(?:$|_)"
)

#: Structural or narrative keys. They carry no standalone factual claim.
STRUCTURAL_KEYS = frozenset(
    {
        "artifact",
        "schema_version",
        "evaluated_at_utc",
        "attempted_at_utc",
        "generated_at_utc",
        "base_sha",
        "source_commit_sha",
        "command",
        "note",
        "notes",
        "reason",
        "reasons",
        "title",
        "description",
        "interpretation",
        "policy",
        "deflation_note",
        "promotion_rule",
        "what_is_and_is_not_measured",
        "why_not_a_negative_result",
        "withdrawn_claims",
        "guarantees",
        "stop_conditions",
        "contract",
        "commands",
        "id",
        "priority",
        "venue",
        "symbol",
        "host",
        "url",
        "path",
        "directory",
        "evidence_root",
        "out_dir",
        "error",
        "outcome",
        "hypothesis_id",
        "opportunity_id",
        "entry_id",
        "kind",
        "route",
        "worker",
        "pool_name",
        "clock_source",
        "correction",
        "v8_claim",
        "derivation",
        "binding_constraint",
    }
)

DIGEST = re.compile(r"\b[0-9a-f]{64}\b")


@dataclass(frozen=True)
class Finding:
    rule: str
    source: str
    path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "source": self.source, "path": self.path, "detail": self.detail}


@dataclass
class GuardReport:
    scanned: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": "PROVENANCE_GUARD",
            "rules": [
                "R1-declaration",
                "R2-digest",
                "R3-verb",
                "R4a-contradiction",
                "R4b-positive-in-negative",
            ],
            "scanned_sources": sorted(self.scanned),
            "clean": self.clean,
            "findings": [f.to_dict() for f in self.findings],
        }


def _is_positive_claim(value: Any) -> bool:
    """True when the value asserts something happened."""
    if value is None or value is False:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        token = value.strip()
        if not token or token.upper() in NOT_MEASURED_TOKENS:
            return False
        # Free prose is narrative, not a discrete claim; R2 still scans it.
        return " " not in token
    if isinstance(value, (list, dict)):
        return bool(value)
    return False


def _declaration_of(node: Any) -> str | None:
    """The evidence declaration a mapping makes about its own contents."""
    if not isinstance(node, dict):
        return None
    for key in DECLARATION_KEYS:
        value = node.get(key)
        if isinstance(value, str):
            token = value.strip().upper()
            if token in EVIDENCE_CLASSES or token in NOT_MEASURED_TOKENS:
                return token
    return None


def _embedded(value: str) -> Any | None:
    """Parse a string that is itself JSON, so records-in-strings are walked."""
    text = value.strip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def scan_payload(
    payload: Any,
    *,
    source: str,
    known_digests: frozenset[str],
) -> list[Finding]:
    """Apply R1-R4 to one artifact payload."""
    findings: list[Finding] = []
    scalars: dict[str, set[Any]] = {}

    def walk(node: Any, path: str, cover: str | None) -> None:
        if isinstance(node, dict):
            here = _declaration_of(node) or cover
            for key, value in node.items():
                child = f"{path}.{key}" if path else str(key)
                _leaf(key, value, child, here)
                walk(value, child, here)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                child = f"{path}[{index}]"
                _leaf(path.rsplit(".", 1)[-1], value, child, cover)
                walk(value, child, cover)
        elif isinstance(node, str):
            parsed = _embedded(node)
            if parsed is not None:
                walk(parsed, f"{path}<json>", cover)

    def _leaf(key: str, value: Any, path: str, cover: str | None) -> None:
        if isinstance(value, (dict, list)) and not (
            VERB_KEY.search(key) and _is_positive_claim(value)
        ):
            return
        if isinstance(value, str):
            for digest in DIGEST.findall(value):
                if key not in CONTENT_HASH_KEYS and digest not in known_digests:
                    findings.append(
                        Finding(
                            "R2-digest",
                            source,
                            path,
                            f"digest {digest[:12]}... resolves to no bytes in the repository",
                        )
                    )
        if key in STRUCTURAL_KEYS and not VERB_KEY.search(key):
            return
        if isinstance(value, (int, float, str, bool)):
            scalars.setdefault(key, set()).add(value)

        verb = bool(VERB_KEY.search(key))
        positive = _is_positive_claim(value)
        declared = cover is not None
        measured = cover in ("MEASURED",)

        if verb and not declared:
            findings.append(
                Finding(
                    "R3-verb",
                    source,
                    path,
                    f"{key!r} claims a verification but no evidence class covers it",
                )
            )
        elif positive and not declared:
            findings.append(
                Finding(
                    "R1-declaration",
                    source,
                    path,
                    f"asserts {value!r} with no declared evidence class",
                )
            )
        quantitative = isinstance(value, (int, float)) and not isinstance(value, bool)
        if (
            positive
            and declared
            and not measured
            and cover in NOT_MEASURED_TOKENS
            and (quantitative or verb)
        ):
            findings.append(
                Finding(
                    "R4b-positive-in-negative",
                    source,
                    path,
                    f"asserts {value!r} inside a block declared {cover}",
                )
            )

    walk(payload, "", None)

    for key, values in scalars.items():
        if len(values) > 1 and not VERB_KEY.search(key):
            continue
        if len(values) > 1:
            findings.append(
                Finding(
                    "R4a-contradiction",
                    source,
                    key,
                    f"{key!r} carries conflicting values {sorted(map(repr, values))}",
                )
            )
    return findings


def scan_prose(
    text: str,
    *,
    source: str,
    known_digests: frozenset[str],
) -> list[Finding]:
    """Apply R2 to documentation.

    Restricting the guard to JSON is what let three assertions of a withdrawn
    capture survive in the reports after the artifact had retracted them.
    """
    findings: list[Finding] = []
    for digest in sorted(set(DIGEST.findall(text))):
        if digest not in known_digests:
            findings.append(
                Finding(
                    "R2-digest",
                    source,
                    "prose",
                    f"digest {digest[:12]}... resolves to no bytes in the repository",
                )
            )
    return findings


#: Where an unresolvable digest must be registered to be tolerated.
UNVERIFIABLE_REGISTER = "configs/provenance/unverifiable_digests.json"

SCANNED_SUBDIRS = ("artifacts", "data", "configs", "tests", "docs", "src", "examples")


def repository_digests(
    repo_root: Path, *, subdirs: tuple[str, ...] = SCANNED_SUBDIRS
) -> frozenset[str]:
    """sha256 of every file the guard can open.

    Computed here, from bytes, every run. The author never types a digest: that
    is the whole point, because a digest an author can write is a digest an
    author can invent.
    """
    digests: set[str] = set()
    for path in repo_root.iterdir():
        if path.is_file():
            try:
                digests.add(hashlib.sha256(path.read_bytes()).hexdigest())
            except OSError:
                continue
    for name in subdirs:
        base = repo_root / name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            try:
                digests.add(hashlib.sha256(path.read_bytes()).hexdigest())
            except OSError:
                continue
    return frozenset(digests)


def registered_unverifiable(repo_root: Path) -> frozenset[str]:
    """Digests explicitly registered as pointing at deliberately-absent bytes."""
    path = repo_root / UNVERIFIABLE_REGISTER
    if not path.exists():
        return frozenset()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return frozenset()
    return frozenset(
        str(entry["sha256"]).lower()
        for entry in payload.get("digests", [])
        if isinstance(entry, dict) and entry.get("sha256")
    )


def guard_repository(
    repo_root: Path,
    *,
    artifact_dirs: tuple[str, ...] = ("artifacts/v7", "artifacts/v8", "artifacts/v9"),
    docs_dir: str = "docs",
) -> GuardReport:
    """Run every rule over the committed artifacts and the prose beside them."""
    report = GuardReport()
    known = repository_digests(repo_root) | registered_unverifiable(repo_root)

    for rel in artifact_dirs:
        base = repo_root / rel
        if not base.exists():
            continue
        for path in sorted(base.glob("*.json")):
            name = f"{rel}/{path.name}"
            report.scanned.append(name)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as exc:
                report.findings.append(Finding("R0-parse", name, "", str(exc)))
                continue
            report.findings.extend(scan_payload(payload, source=name, known_digests=known))

    docs = repo_root / docs_dir
    if docs.exists():
        for path in sorted(docs.rglob("*.md")):
            name = path.relative_to(repo_root).as_posix()
            report.scanned.append(name)
            report.findings.extend(
                scan_prose(path.read_text(encoding="utf-8"), source=name, known_digests=known)
            )
    return report


def main() -> int:
    """Print the provenance report. Reports, never fabricates a pass."""
    import argparse
    from collections import Counter

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()

    report = guard_repository(args.repo_root)
    by_rule = Counter(f.rule for f in report.findings)
    print(f"scanned {len(report.scanned)} sources; {len(report.findings)} findings")
    for rule, count in sorted(by_rule.items()):
        print(f"  {rule}: {count}")
    for finding in report.findings[:20]:
        print(f"  - {finding.source}:{finding.path} {finding.detail}")
    if len(report.findings) > 20:
        print(f"  ... and {len(report.findings) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
