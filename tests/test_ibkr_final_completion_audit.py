from pathlib import Path
from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_final_completion_audit as module


def test_final_audit_controls_only_verified_flat_symbols():
    assert module.CONTROLLED_SYMBOLS == ("SPY", "AAPL", "9432")


def test_broker_quantity_sums_only_requested_symbol():
    account = SimpleNamespace(
        positions=(
            SimpleNamespace(symbol="SPY", quantity=1.0),
            SimpleNamespace(symbol="SPY", quantity=2.0),
            SimpleNamespace(symbol="9432", quantity=100.0),
        )
    )
    assert module._broker_quantity(account, "SPY") == 3.0
    assert module._broker_quantity(account, "AAPL") == 0.0


def test_final_audit_source_contains_no_order_transmission_path():
    text = Path(
        "src/ai_asset_platform/brokers/ibkr_final_completion_audit.py"
    ).read_text(encoding="utf-8")
    assert "placeOrder(" not in text
    assert "execute_ibkr_paper_order" not in text
    assert "transmit_ibkr_paper_order" not in text
    assert "enable_paper_order_transmission=True" not in text


def test_final_audit_wrapper_preserves_default_safe_test_environment():
    text = Path("ibkr_final_completion_audit_once.sh").read_text(encoding="utf-8")
    pytest_index = text.index("python -m pytest -q")
    audit_index = text.index(
        "python -m ai_asset_platform.brokers.ibkr_final_completion_audit"
    )
    assert pytest_index < audit_index
    assert "AI_ASSET_ENABLE_IBKR_PAPER=1" not in text
    assert "AI_ASSET_ENABLE_LIVE_TRADING=1" not in text
    assert "AI_ASSET_LIVE_TRADING_UNLOCKED=1" not in text
    assert "IBKR_9432_CLOSE_CONFIRM" not in text
    assert "IBKR_AAPL_RESET_CONFIRM" not in text
    assert "IBKR_AUTO_CLOSE_CONFIRM" not in text
