from pathlib import Path


def test_readonly_soak_wrapper_never_enables_order_transmission():
    text = Path("ibkr_readonly_soak_once.sh").read_text(encoding="utf-8")

    assert "bash ./ibkr_auto.sh" in text
    assert "python -m pytest -q" in text
    assert "IBKR_SOAK_CYCLES" in text
    assert "IBKR_SOAK_INTERVAL_SECONDS" in text

    forbidden = (
        "IBKR_AAPL_RESET_CONFIRM=",
        "IBKR_AUTO_CLOSE_CONFIRM=",
        "AI_ASSET_ALLOW_ONE_OVERNIGHT_PAPER_E2E=true",
        "AI_ASSET_ENABLE_IBKR_PAPER=1",
        "AI_ASSET_ENABLE_LIVE_TRADING=1",
        "AI_ASSET_LIVE_TRADING_UNLOCKED=1",
        "ibkr_aapl_flat_reset_once.sh",
        "ibkr_auto_close_cycle_once.sh",
        "ibkr_overnight_e2e_once.sh",
    )
    for marker in forbidden:
        assert marker not in text


def test_readonly_soak_wrapper_is_bounded_not_infinite():
    text = Path("ibkr_readonly_soak_once.sh").read_text(encoding="utf-8")
    assert "while true" not in text
    assert "CYCLES < 2 || CYCLES > 20" in text
    assert "for ((cycle=1; cycle<=CYCLES; cycle++))" in text


def test_readonly_soak_requires_main_but_can_run_when_origin_is_unavailable():
    text = Path("ibkr_readonly_soak_once.sh").read_text(encoding="utf-8")
    switch_at = text.index("git switch main")
    pull_at = text.index("if git pull --ff-only origin main; then")
    warning_at = text.index("origin/main unavailable; continuing bounded read-only soak")
    pytest_at = text.index("python -m pytest -q")
    assert switch_at < pull_at < warning_at < pytest_at
