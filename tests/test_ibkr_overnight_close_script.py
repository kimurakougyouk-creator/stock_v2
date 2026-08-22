from pathlib import Path
import subprocess


def test_close_script_has_valid_bash_syntax():
    script = Path("ibkr_overnight_close_once.sh")
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_close_script_requires_explicit_confirmation_and_paper_only_flags():
    text = Path("ibkr_overnight_close_once.sh").read_text(encoding="utf-8")
    assert "YES_CLOSE_ONE_SPY_PAPER" in text
    assert "AI_ASSET_ENABLE_IBKR_PAPER=true" in text
    assert "AI_ASSET_ENABLE_IBKR_OVERNIGHT_CLOSE_E2E=true" in text
    assert "ibkr_overnight_close_e2e" in text
    assert "git reset" not in text
    assert "git clean" not in text
    assert "git stash" not in text
    assert "placeOrder" not in text
    assert "cancelOrder" not in text
