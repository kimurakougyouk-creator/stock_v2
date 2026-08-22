from pathlib import Path


def test_close_cycle_wrapper_runs_followup_checkpoint_after_success():
    text = Path("ibkr_close_cycle_once.sh").read_text(encoding="utf-8")
    assert "ibkr_close_cycle" in text
    assert "ibkr_auto.sh" in text
    assert "No order was sent" in text
