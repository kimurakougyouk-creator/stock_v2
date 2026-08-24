from pathlib import Path


def test_safe_paper_e2e_wrapper_preserves_fail_closed_invariants():
    text = Path("ibkr_safe_paper_e2e_once.sh").read_text(encoding="utf-8")

    assert "YES_RETIRE_STALE_AND_BUY_ONE_SPY_PAPER" in text
    assert "python -m pytest -q" in text
    assert "AI_ASSET_ALLOW_STALE_LEGACY_RETIREMENT=true" in text
    assert "ibkr_legacy_fill_retirement_cli" in text
    assert "ibkr_operator_checkpoint" in text
    assert "AI_ASSET_ALLOW_ONE_OVERNIGHT_PAPER_E2E=true" in text
    assert "ibkr_overnight_e2e_once.sh" in text
    assert "git pull --ff-only origin main" in text
    assert "git reset" not in text
    assert "git clean" not in text
    assert "git stash" not in text
    assert "enable_live" not in text.lower()
