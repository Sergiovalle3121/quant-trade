from pathlib import Path

from quant_trade.security.secret_scan import scan_paths


def test_fake_secret_detected(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("token: Bearer abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    report = scan_paths([p])
    assert report.status == "fail"
    assert report.findings[0].preview.startswith("[REDACTED")
    assert "abcdefghijklmnopqrstuvwxyz" not in report.findings[0].preview


def test_env_example_placeholders_allowed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    Path(".env.example").write_text("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")
    report = scan_paths([Path(".env.example")])
    assert report.status == "pass"
