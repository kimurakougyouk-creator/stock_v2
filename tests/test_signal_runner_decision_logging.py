from pathlib import Path


def test_signal_runner_calls_log_decision():
    source = Path("signal_runner.py").read_text(
        encoding="utf-8"
    )

    assert "log_decision(" in source
    assert "ticker=ticker" in source
    assert "final_signal=final_decision.signal" in source
    assert "technical_signal=signal_result" in source
