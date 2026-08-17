from pathlib import Path


def test_decision_logging_uses_single_ordered_state():
    source = Path("signal_runner.py").read_text(
        encoding="utf-8"
    )

    assert "decision_ordered = False" in source
    assert "decision_ordered = True" in source
    assert "ordered=decision_ordered" in source

    # Paper注文成立時に別のordered=Trueログを
    # 直接書かないことを確認する。
    assert "ordered=True," not in source
