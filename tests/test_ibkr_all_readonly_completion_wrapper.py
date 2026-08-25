from pathlib import Path


def _wrapper_text() -> str:
    return Path("ibkr_all_readonly_completion_once.sh").read_text(encoding="utf-8")


def test_wrapper_runs_all_product_audits_through_aggregate_runner():
    text = _wrapper_text()
    assert 'run_readonly_step "pytest"' in text
    assert 'run_readonly_step "stock-etf-global-stock"' in text
    assert 'run_readonly_step "futures-postfill"' in text
    assert 'run_readonly_step "options-postfill"' in text
    assert 'run_readonly_step "crypto-visibility"' in text
    assert "READ-ONLY FAILED STEPS" in text
    assert "FINAL READ-ONLY GATE" in text


def test_wrapper_does_not_fail_fast_before_later_readonly_audits():
    text = _wrapper_text()
    assert "set -e" not in text
    futures_index = text.index('run_readonly_step "futures-postfill"')
    option_index = text.index('run_readonly_step "options-postfill"')
    crypto_index = text.index('run_readonly_step "crypto-visibility"')
    assert futures_index < option_index < crypto_index


def test_wrapper_contains_no_order_enable_or_confirmation_flags():
    text = _wrapper_text()
    forbidden = (
        "AI_ASSET_ENABLE_IBKR_PAPER=1",
        "AI_ASSET_ENABLE_LIVE_TRADING=1",
        "AI_ASSET_LIVE_TRADING_UNLOCKED=1",
        "IBKR_FUTURE_E2E_CONFIRM",
        "IBKR_OPTION_E2E_CONFIRM",
        "IBKR_AUTO_CLOSE_CONFIRM",
        "IBKR_9432_CLOSE_CONFIRM",
        "IBKR_AAPL_RESET_CONFIRM",
    )
    for token in forbidden:
        assert token not in text
