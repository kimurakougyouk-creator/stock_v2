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


def test_dedicated_derivative_and_option_execs_are_excluded_from_legacy_stock_accounting():
    option_sell = {
        "broker_exec_ids": ["00020057.6a8c86b3.01.01"],
        "ticker": "SPY",
        "side": "SELL",
    }
    future_buy = {
        "broker_exec_ids": ["0000e1a7.6a8f948c.01.01"],
        "ticker": "ES",
        "side": "BUY",
    }
    ordinary_spy = {
        "broker_exec_ids": ["00012ec5.6ab91096.01.01"],
        "ticker": "SPY",
        "side": "BUY",
    }
    assert module._belongs_to_dedicated_audit(option_sell)
    assert module._belongs_to_dedicated_audit(future_buy)
    assert not module._belongs_to_dedicated_audit(ordinary_spy)
    assert module._aggregate_stock_records([option_sell, future_buy, ordinary_spy]) == [ordinary_spy]


def test_final_audit_reuses_one_execution_snapshot_for_idempotency_proof():
    text = Path(
        "src/ai_asset_platform/brokers/ibkr_final_completion_audit.py"
    ).read_text(encoding="utf-8")
    assert text.count("preview_ibkr_paper_execution_snapshot()") == 1


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
