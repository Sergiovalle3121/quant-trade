from __future__ import annotations

import math
import re
from pathlib import Path

from quant_trade.security.config import load_yaml
from quant_trade.security.models import Finding, SecurityReport
from quant_trade.security.redaction import redacted_preview

PATTERNS = [
    ("aws_access_key", "critical", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("alpaca_key", "critical", re.compile(r"APCA-[A-Z0-9]{16,}")),
    ("bearer_token", "critical", re.compile(r"Bearer\s+([A-Za-z0-9._~+/=-]{20,})")),
    ("private_key", "critical", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "api_key_assignment",
        "high",
        re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([^'\"\s]{12,})"),
    ),
]
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".jsonl",
    ".toml",
    ".txt",
    ".env",
    ".example",
}


def entropy(value: str) -> float:
    if not value:
        return 0.0
    total = 0.0
    for char in set(value):
        probability = value.count(char) / len(value)
        total -= probability * math.log2(probability)
    return total


def _allowlist() -> set[str]:
    values = {"CHANGE_ME", "REPLACE_ME", "example", "placeholder", "dummy", "test"}
    env = Path(".env.example")
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line:
                values.add(line.split("=", 1)[1].strip().strip("\"'"))
    return values


def iter_scan_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    skip_parts = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__", "outputs"}
    for root in roots:
        if root.is_file():
            files.append(root)
            continue
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or any(part in skip_parts for part in path.parts):
                continue
            if path.suffix in TEXT_SUFFIXES or path.name.startswith(".env"):
                files.append(path)
    return sorted(set(files))


def _allowed(value: str, allow: set[str]) -> bool:
    return any(a and a.lower() in value.lower() for a in allow)


def scan_paths(paths: list[Path]) -> SecurityReport:
    allow = _allowlist()
    findings: list[Finding] = []
    for path in iter_scan_files(paths):
        rel = str(path)
        if path.name == ".env":
            findings.append(
                Finding("env_file", "critical", rel, 1, ".env prohibited", "[REDACTED]")
            )
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for rule, severity, pattern in PATTERNS:
                match = pattern.search(line)
                if match:
                    value = match.group(match.lastindex or 0)
                    if _allowed(value, allow):
                        continue
                    findings.append(
                        Finding(
                            rule,
                            severity,
                            rel,
                            line_no,
                            "Potential secret",
                            redacted_preview(value),
                        )
                    )
            for token in re.findall(r"[A-Za-z0-9_\-+/=]{40,}", line):
                if entropy(token) >= 4.5 and not _allowed(token, allow):
                    findings.append(
                        Finding(
                            "high_entropy",
                            "high",
                            rel,
                            line_no,
                            "High entropy",
                            redacted_preview(token),
                        )
                    )
    status = "fail" if any(f.severity == "critical" for f in findings) else "pass"
    return SecurityReport(status=status, findings=findings)


def scan_from_config(config_path: Path) -> SecurityReport:
    cfg = load_yaml(config_path)
    default = ["src", "tests", "configs", "docs", "README.md", "AGENTS.md"]
    roots = [Path(p) for p in cfg.get("scan_paths", default)]
    return scan_paths(roots)
