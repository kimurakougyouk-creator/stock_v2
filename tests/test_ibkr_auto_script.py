from pathlib import Path
import subprocess


def test_ibkr_auto_script_has_valid_bash_syntax():
    script = Path("ibkr_auto.sh")
    assert script.exists()
    result = subprocess.run(
        ["bash", "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_ibkr_auto_script_preserves_fail_closed_operator_flow():
    text = Path("ibkr_auto.sh").read_text(encoding="utf-8")
    assert "git pull --ff-only origin main" in text
    assert "git reset" not in text
    assert "git clean" not in text
    assert "git stash" not in text
    assert "ai_asset_platform.brokers.ibkr_operator_checkpoint" in text
    assert "ai_asset_platform.brokers.ibkr_execution_snapshot" in text
    assert "reconcile_execution_snapshot_to_ledger" in text
    assert "IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE" in text
    assert "ibkr_execution_snapshot_latest.log" in text
    assert "ibkr_execution_reconcile_latest.log" in text
    assert "4002" in text
    assert "7497" in text
    assert "placeOrder" not in text
    assert "cancelOrder" not in text
    assert "REAL ORDER SENT  : False" in text
