from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_foundation_audit_runs_security_tests_and_no_transmit_smoke():
    text = (ROOT / "scripts" / "audit_foundation.sh").read_text(encoding="utf-8")
    assert "python scripts/check_secrets.py" in text
    assert "pytest -q" in text
    assert "ibkr_paper_smoke_test" in text
    assert "paper_trading_runner.py" not in text
    assert "ENABLE_LIVE" not in text
