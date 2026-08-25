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
    assert "git switch main" in text
    assert "if git pull --ff-only origin main; then" in text
    assert "continuing this read-only cycle from unchanged local main" in text
    assert "git reset" not in text
    assert "git clean" not in text
    assert "git stash" not in text
    assert "ai_asset_platform.execution.ibkr_execution_reconcile" in text
    assert "ai_asset_platform.brokers.ibkr_operator_checkpoint" in text
    assert "ai_asset_platform.brokers.ibkr_multiasset_readonly_audit" in text
    assert "IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE" in text
    assert "ibkr_execution_reconcile_latest.log" in text
    assert "ibkr_operator_checkpoint_latest.log" in text
    assert "ibkr_multiasset_readonly_audit_latest.log" in text
    assert "4002" in text
    assert "7497" in text
    assert "placeOrder" not in text
    assert "cancelOrder" not in text
    assert "YES_CLOSE_ONE_SPY_PAPER" not in text
    assert "AI_ASSET_ENABLE_IBKR_PAPER=true" not in text
    assert "AI_ASSET_ENABLE_LIVE_TRADING" not in text
    assert "AI_ASSET_LIVE_TRADING_UNLOCKED" not in text


def test_remote_update_failure_is_nonfatal_only_after_main_is_required():
    text = Path("ibkr_auto.sh").read_text(encoding="utf-8")
    switch_at = text.index("git switch main")
    pull_at = text.index("if git pull --ff-only origin main; then")
    warning_at = text.index("continuing this read-only cycle from unchanged local main")
    venv_at = text.index(".venv/bin/activate")
    assert switch_at < pull_at < warning_at < venv_at


def test_multiasset_readonly_status_is_diagnostic_not_order_permission():
    text = Path("ibkr_auto.sh").read_text(encoding="utf-8")
    assert "multiasset_status=${PIPESTATUS[0]}" in text
    assert ': "$multiasset_status"' in text
    assert 'exit "$checkpoint_status"' in text
