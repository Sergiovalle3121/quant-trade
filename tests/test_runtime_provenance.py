from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import quant_trade.research.runtime_provenance as provenance_module
from quant_trade.research.runtime_provenance import (
    RuntimeCodeProvenance,
    RuntimeProvenanceError,
    verify_runtime_code_commit,
)

COMMIT = "a" * 40


class _FakeProvider:
    def __init__(self, value: RuntimeCodeProvenance | Exception) -> None:
        self.value = value
        self.calls = 0

    def inspect(self) -> RuntimeCodeProvenance:
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def _observed(*, commit: str = COMMIT, clean: bool = True) -> RuntimeCodeProvenance:
    return RuntimeCodeProvenance(
        code_commit=commit,
        source_mode="git-checkout",
        source_tree_digest="b" * 40,
        clean=clean,
        source_root=str(Path.cwd().resolve()),
    )


def test_verify_runtime_commit_uses_private_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider(_observed())
    monkeypatch.setattr(provenance_module, "_PROVIDER", provider)

    result = verify_runtime_code_commit(COMMIT)

    assert result.code_commit == COMMIT
    assert result.clean is True
    assert provider.calls == 1


@pytest.mark.parametrize(
    ("observed", "message"),
    [
        (_observed(commit="c" * 40), "does not match"),
        (_observed(clean=False), "completely clean"),
    ],
)
def test_verify_runtime_commit_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    observed: RuntimeCodeProvenance,
    message: str,
) -> None:
    monkeypatch.setattr(provenance_module, "_PROVIDER", _FakeProvider(observed))

    with pytest.raises(RuntimeProvenanceError, match=message):
        verify_runtime_code_commit(COMMIT)


def test_verify_runtime_commit_rejects_short_spec_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider(_observed())
    monkeypatch.setattr(provenance_module, "_PROVIDER", provider)

    with pytest.raises(RuntimeProvenanceError, match="full 40- or 64-character"):
        verify_runtime_code_commit("a" * 7)

    assert provider.calls == 0


def test_provider_exception_is_never_treated_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        provenance_module,
        "_PROVIDER",
        _FakeProvider(OSError("inspection unavailable")),
    )

    with pytest.raises(RuntimeProvenanceError, match="inspection failed"):
        verify_runtime_code_commit(COMMIT)


def test_environment_provider_rejects_unsigned_build_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_module_path: Path) -> RuntimeCodeProvenance:
        raise provenance_module._NotGitCheckout("no git metadata")

    monkeypatch.setattr(provenance_module, "_inspect_git_checkout", unavailable)

    with pytest.raises(RuntimeProvenanceError, match="unsigned build metadata is not accepted"):
        provenance_module._EnvironmentRuntimeProvenanceProvider().inspect()


def _write_build_manifest(package_root: Path, *, commit: str = COMMIT) -> Path:
    files = {
        path.relative_to(package_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in package_root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".pyi"}
    }
    tree_digest = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    metadata = {
        "schema_version": 1,
        "code_commit": commit,
        "source_tree_digest": tree_digest,
        "files": files,
    }
    path = package_root / provenance_module.BUILD_PROVENANCE_FILENAME
    path.write_text(json.dumps(metadata), encoding="utf-8")
    return path


def test_build_metadata_binds_every_python_source_byte(tmp_path: Path) -> None:
    package_root = tmp_path / "quant_trade"
    (package_root / "research").mkdir(parents=True)
    (package_root / "__init__.py").write_text("VERSION = 1\n", encoding="utf-8")
    source = package_root / "research" / "model.py"
    source.write_text("EDGE = False\n", encoding="utf-8")
    _write_build_manifest(package_root)

    result = provenance_module._inspect_build_metadata(package_root)

    assert result.code_commit == COMMIT
    assert result.source_mode == "build-metadata"
    assert result.clean is True

    source.write_text("EDGE = True\n", encoding="utf-8")
    with pytest.raises(RuntimeProvenanceError, match="source bytes do not match"):
        provenance_module._inspect_build_metadata(package_root)


def test_build_metadata_rejects_unattested_python_file(tmp_path: Path) -> None:
    package_root = tmp_path / "quant_trade"
    package_root.mkdir()
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    _write_build_manifest(package_root)
    (package_root / "shadow.py").write_text("SHADOW = True\n", encoding="utf-8")

    with pytest.raises(RuntimeProvenanceError, match="exact Python source tree"):
        provenance_module._inspect_build_metadata(package_root)


def test_git_checkout_rejects_ignored_or_untracked_python_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = tmp_path / "src" / "quant_trade" / "research" / "runtime_provenance.py"
    module.parent.mkdir(parents=True)
    module.write_text("", encoding="utf-8")
    hidden = module.parents[1] / "ignored_shadow.py"
    hidden.write_text("SHADOW = True\n", encoding="utf-8")
    relative_module = module.relative_to(tmp_path).as_posix()

    def fake_git(_start: Path, *arguments: str) -> str:
        if arguments == ("rev-parse", "--show-toplevel"):
            return str(tmp_path)
        if arguments[:2] == ("ls-files", "--error-unmatch"):
            return relative_module
        if arguments == ("ls-files", "--", "src/quant_trade"):
            # Simulate an ignored source: it exists on disk but Git does not
            # report it, even though normal porcelain status may be clean.
            return relative_module
        raise AssertionError(f"unexpected git call: {arguments}")

    monkeypatch.setattr(provenance_module, "_run_git", fake_git)

    with pytest.raises(RuntimeProvenanceError, match="tracked source set"):
        provenance_module._inspect_git_checkout(module)


def test_git_checkout_binds_clean_head_and_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = tmp_path / "src" / "quant_trade" / "research" / "runtime_provenance.py"
    module.parent.mkdir(parents=True)
    module.write_text("ATTESTED = True\n", encoding="utf-8")
    relative_module = module.relative_to(tmp_path).as_posix()

    def fake_git(_start: Path, *arguments: str) -> str:
        responses = {
            ("rev-parse", "--show-toplevel"): str(tmp_path),
            ("ls-files", "--error-unmatch", relative_module): relative_module,
            ("ls-files", "--", "src/quant_trade"): relative_module,
            ("rev-parse", "HEAD"): COMMIT,
            ("rev-parse", "HEAD^{tree}"): "b" * 40,
            (
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ): "",
        }
        return responses[arguments]

    monkeypatch.setattr(provenance_module, "_run_git", fake_git)
    result = provenance_module._inspect_git_checkout(module)

    assert result == RuntimeCodeProvenance(
        code_commit=COMMIT,
        source_mode="git-checkout",
        source_tree_digest="b" * 40,
        clean=True,
        source_root=str(tmp_path.resolve()),
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "schema_version": 999,
            "code_commit": COMMIT,
            "source_tree_digest": "b" * 64,
            "files": {"__init__.py": "c" * 64},
        },
        {
            "schema_version": 1,
            "code_commit": COMMIT,
            "source_tree_digest": "bad",
            "files": {"__init__.py": "c" * 64},
        },
        {
            "schema_version": 1,
            "code_commit": COMMIT,
            "source_tree_digest": "b" * 64,
            "files": {"../escape.py": "c" * 64},
        },
    ],
)
def test_build_manifest_rejects_malformed_contract(tmp_path: Path, payload: object) -> None:
    package_root = tmp_path / "quant_trade"
    package_root.mkdir()
    (package_root / "__init__.py").write_text("", encoding="utf-8")

    with pytest.raises(RuntimeProvenanceError):
        provenance_module._parse_build_manifest(package_root, payload)
