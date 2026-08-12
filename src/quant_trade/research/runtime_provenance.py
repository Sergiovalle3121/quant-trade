"""Fail-closed provenance for the Python code executing protected research.

An ``ExperimentSpec.code_commit`` is only a declaration.  This module binds
that declaration to the code which is actually imported before a protected
P&L run may start:

* in a Git checkout, the exact ``HEAD`` must match and the complete worktree
  (including untracked files and submodules) must be clean;
Installed builds without independently verifiable Git metadata fail closed.
An unsigned file placed beside the package is not an attestation and is never
accepted as a substitute for repository provenance.

The provider is deliberately private and the public verifier accepts no
caller-supplied provenance or bypass flag.  Tests replace the private provider
at the module boundary; production callers can only provide the expected
commit from the sealed experiment specification.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

BUILD_PROVENANCE_FILENAME = "_build_provenance.json"
BUILD_PROVENANCE_SCHEMA_VERSION = 1
_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SOURCE_SUFFIXES = frozenset({".py", ".pyi"})


class RuntimeProvenanceError(RuntimeError):
    """Raised when the executed source cannot be bound to a clean commit."""


@dataclass(frozen=True)
class RuntimeCodeProvenance:
    """Verified identity of the code currently executing the research run."""

    code_commit: str
    source_mode: str
    source_tree_digest: str
    clean: bool
    source_root: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_commit": self.code_commit,
            "source_mode": self.source_mode,
            "source_tree_digest": self.source_tree_digest,
            "clean": self.clean,
        }


class _RuntimeProvenanceProvider(Protocol):
    def inspect(self) -> RuntimeCodeProvenance: ...


class _NotGitCheckout(RuntimeError):
    """Internal signal allowing the immutable-build fallback."""


def _run_git(start: Path, *arguments: str) -> str:
    command = ["git", "-C", str(start), *arguments]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise _NotGitCheckout("Git metadata is unavailable") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise _NotGitCheckout(detail or "path is not inside a Git checkout")
    return completed.stdout.strip()


def _validate_commit(value: object, *, field: str) -> str:
    normalized = str(value).strip().lower()
    if not _COMMIT_RE.fullmatch(normalized):
        raise RuntimeProvenanceError(
            f"{field} must be a full 40- or 64-character hexadecimal commit id"
        )
    return normalized


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_manifest_digest(files: Mapping[str, str]) -> str:
    payload = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _inspect_git_checkout(module_path: Path) -> RuntimeCodeProvenance:
    search_root = module_path.parent
    root_text = _run_git(search_root, "rev-parse", "--show-toplevel")
    root = Path(root_text).resolve()
    package_root = module_path.parents[1].resolve()
    try:
        relative_module = module_path.resolve().relative_to(root)
        relative_package = package_root.relative_to(root)
    except ValueError as exc:
        raise RuntimeProvenanceError(
            "the imported runtime module is outside the discovered Git checkout"
        ) from exc

    # Ensure Git considers the executing module part of this checkout.  A
    # shadow/untracked package next to a repository must never inherit HEAD.
    tracked = _run_git(root, "ls-files", "--error-unmatch", relative_module.as_posix())
    if not tracked:
        raise RuntimeProvenanceError("the imported runtime module is not tracked by Git")

    # Git's normal status output intentionally hides ignored paths.  An ignored
    # ``.py`` could nevertheless win import resolution, so compare the complete
    # on-disk package with the files tracked by the attested commit.  Symlinks
    # are forbidden because their target bytes can live outside the checkout.
    actual_sources: set[str] = set()
    for path in package_root.rglob("*"):
        if path.is_file() and path.suffix in _SOURCE_SUFFIXES:
            if path.is_symlink():
                raise RuntimeProvenanceError("runtime Python sources may not be symbolic links")
            actual_sources.add(path.relative_to(root).as_posix())
    tracked_output = _run_git(root, "ls-files", "--", relative_package.as_posix())
    tracked_sources = {
        name
        for name in tracked_output.splitlines()
        if PurePosixPath(name).suffix in _SOURCE_SUFFIXES
    }
    if actual_sources != tracked_sources:
        raise RuntimeProvenanceError(
            "the runtime Python package differs from Git's tracked source set"
        )

    head = _validate_commit(_run_git(root, "rev-parse", "HEAD"), field="Git HEAD")
    tree_oid = _run_git(root, "rev-parse", "HEAD^{tree}").lower()
    if not _COMMIT_RE.fullmatch(tree_oid):
        raise RuntimeProvenanceError("Git returned an invalid source-tree object id")

    status = _run_git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    return RuntimeCodeProvenance(
        code_commit=head,
        source_mode="git-checkout",
        source_tree_digest=tree_oid,
        clean=not bool(status),
        source_root=str(root),
    )


def _parse_build_manifest(package_root: Path, payload: object) -> RuntimeCodeProvenance:
    if not isinstance(payload, Mapping):
        raise RuntimeProvenanceError("build provenance must be a JSON object")
    allowed = {"schema_version", "code_commit", "source_tree_digest", "files"}
    unknown = sorted(set(payload) - allowed)
    missing = sorted(allowed - set(payload))
    if unknown or missing:
        raise RuntimeProvenanceError(
            f"invalid build provenance fields (missing={missing}, unknown={unknown})"
        )
    if payload["schema_version"] != BUILD_PROVENANCE_SCHEMA_VERSION:
        raise RuntimeProvenanceError("unsupported build provenance schema version")

    commit = _validate_commit(payload["code_commit"], field="build code_commit")
    declared_tree_digest = str(payload["source_tree_digest"]).strip().lower()
    if not _SHA256_RE.fullmatch(declared_tree_digest):
        raise RuntimeProvenanceError("build source_tree_digest must be a SHA-256 digest")

    declared_files = payload["files"]
    if not isinstance(declared_files, Mapping) or not declared_files:
        raise RuntimeProvenanceError("build provenance files must be a non-empty mapping")

    normalized: dict[str, str] = {}
    for raw_name, raw_digest in declared_files.items():
        name = str(raw_name)
        pure = PurePosixPath(name)
        if (
            not name
            or pure.is_absolute()
            or "\\" in name
            or any(part in {"", ".", ".."} for part in pure.parts)
            or pure.suffix not in _SOURCE_SUFFIXES
        ):
            raise RuntimeProvenanceError(f"unsafe build provenance source path: {name!r}")
        digest = str(raw_digest).strip().lower()
        if not _SHA256_RE.fullmatch(digest):
            raise RuntimeProvenanceError(f"invalid source digest for {name!r}")
        if name in normalized:
            raise RuntimeProvenanceError(f"duplicate source path in build provenance: {name!r}")
        normalized[name] = digest

    actual_names = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and path.suffix in _SOURCE_SUFFIXES
    }
    if set(normalized) != actual_names:
        missing_sources = sorted(actual_names - set(normalized))
        extra_sources = sorted(set(normalized) - actual_names)
        raise RuntimeProvenanceError(
            "build provenance does not cover the exact Python source tree "
            f"(missing={missing_sources}, extra={extra_sources})"
        )

    for name, expected_digest in sorted(normalized.items()):
        actual_digest = _sha256_file(package_root.joinpath(*PurePosixPath(name).parts))
        if actual_digest != expected_digest:
            raise RuntimeProvenanceError(f"installed source bytes do not match {name!r}")

    actual_tree_digest = _source_manifest_digest(normalized)
    if actual_tree_digest != declared_tree_digest:
        raise RuntimeProvenanceError("build source-tree digest does not match its file manifest")
    return RuntimeCodeProvenance(
        code_commit=commit,
        source_mode="build-metadata",
        source_tree_digest=actual_tree_digest,
        clean=True,
        source_root=str(package_root.resolve()),
    )


def _inspect_build_metadata(package_root: Path) -> RuntimeCodeProvenance:
    metadata_path = package_root / BUILD_PROVENANCE_FILENAME
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeProvenanceError(
            "runtime is neither a Git checkout nor an attested immutable build"
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeProvenanceError("build provenance metadata cannot be read") from exc
    return _parse_build_manifest(package_root, payload)


class _EnvironmentRuntimeProvenanceProvider:
    def inspect(self) -> RuntimeCodeProvenance:
        module_path = Path(__file__).resolve()
        try:
            return _inspect_git_checkout(module_path)
        except _NotGitCheckout as exc:
            raise RuntimeProvenanceError(
                "protected P&L requires a verifiable Git checkout; unsigned build "
                "metadata is not accepted"
            ) from exc


_PROVIDER: _RuntimeProvenanceProvider = _EnvironmentRuntimeProvenanceProvider()


def verify_runtime_code_commit(expected_commit: str) -> RuntimeCodeProvenance:
    """Verify that the sealed commit is the clean code actually executing.

    There is intentionally no provenance/provider argument and no dirty-tree
    override.  A protected runner should call this before constructing signals
    or evaluating any P&L, then include :meth:`RuntimeCodeProvenance.to_dict`
    in its immutable artifact.
    """

    expected = _validate_commit(expected_commit, field="expected code_commit")
    try:
        observed = _PROVIDER.inspect()
    except RuntimeProvenanceError:
        raise
    except Exception as exc:  # pragma: no cover - defensive fail-closed boundary
        raise RuntimeProvenanceError("runtime code provenance inspection failed") from exc
    observed_commit = _validate_commit(observed.code_commit, field="observed code_commit")
    if observed.clean is not True:
        raise RuntimeProvenanceError("protected P&L requires a completely clean source tree")
    if observed_commit != expected:
        raise RuntimeProvenanceError(
            "sealed code_commit does not match the code currently executing"
        )
    expected_tree_pattern = _COMMIT_RE if observed.source_mode == "git-checkout" else _SHA256_RE
    if observed.source_mode not in {"git-checkout", "build-metadata"}:
        raise RuntimeProvenanceError("runtime provenance has an unsupported source mode")
    if not expected_tree_pattern.fullmatch(observed.source_tree_digest.lower()):
        raise RuntimeProvenanceError("runtime provenance has an invalid source-tree digest")
    if not observed.source_root or not Path(observed.source_root).is_absolute():
        raise RuntimeProvenanceError("runtime provenance is incomplete")
    return observed


__all__ = [
    "BUILD_PROVENANCE_FILENAME",
    "BUILD_PROVENANCE_SCHEMA_VERSION",
    "RuntimeCodeProvenance",
    "RuntimeProvenanceError",
    "verify_runtime_code_commit",
]
