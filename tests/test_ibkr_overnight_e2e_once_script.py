from pathlib import Path


def test_one_command_overnight_e2e_script_safety_invariants():
    text = Path("ibkr_overnight_e2e_once.sh").read_text(encoding="utf-8")
    assert "AI_ASSET_ALLOW_ONE_OVERNIGHT_PAPER_E2E" in text
    assert "AI_ASSET_ENABLE_IBKR_PAPER=true" in text
    assert "AI_ASSET_ENABLE_IBKR_OVERNIGHT_E2E=true" in text
    assert "ibkr_overnight_paper_e2e_cli" in text
    assert "git pull --ff-only origin main" in text
    assert "4002" in text and "7497" in text
    assert "git reset" not in text
    assert "git clean" not in text
    assert "git stash" not in text
    assert "enable_live" not in text.lower()
