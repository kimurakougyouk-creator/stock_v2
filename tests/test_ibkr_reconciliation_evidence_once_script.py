from pathlib import Path


def test_reconciliation_evidence_wrapper_is_read_only_and_targeted():
    text = Path("ibkr_reconciliation_evidence_once.sh").read_text(encoding="utf-8")
    assert "ibkr_reconciliation_evidence_audit" in text
    assert "tests/test_ibkr_reconciliation_evidence_audit.py" in text
    assert "placeOrder" not in text
    assert "ibkr_overnight_e2e_once.sh" not in text
    assert "ibkr_safe_paper_e2e_once.sh" not in text
    assert "git reset" not in text
    assert "git clean" not in text
    assert "git stash" not in text
    assert "AI_ASSET_ALLOW_ONE_OVERNIGHT_PAPER_E2E" not in text
    assert "AI_ASSET_ENABLE_IBKR_OVERNIGHT_CLOSE_E2E" not in text
