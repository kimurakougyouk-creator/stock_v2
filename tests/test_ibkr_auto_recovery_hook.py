from pathlib import Path


def test_ibkr_auto_runs_fail_closed_execution_log_recovery_before_checkpoint():
    script = Path("ibkr_auto.sh").read_text(encoding="utf-8")
    recovery = "python -m ai_asset_platform.execution.ibkr_execution_log_recovery"
    checkpoint = "python -m ai_asset_platform.brokers.ibkr_operator_checkpoint"
    assert recovery in script
    assert checkpoint in script
    assert script.index(recovery) < script.index(checkpoint)
    assert "REAL ORDER SENT" not in script
