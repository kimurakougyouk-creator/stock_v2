from unittest.mock import Mock, patch

import pytest

from ai_asset_platform.brokers.orders import OrderSide
from ai_asset_platform.core.asset_classes import AssetClass
from ai_asset_platform.core.settings import PlatformSettings
from ai_asset_platform.execution.signal_order_bridge import (
    _instrument_for_ticker,
    execute_signal_via_ibkr_paper,
    verified_paper_test_quantity_for_ticker,
)


def test_disabled_ibkr_never_calls_execution_service() -> None:
    service = Mock()
    settings = PlatformSettings(enable_paper_trading=True, enable_ibkr_paper=False)
    with patch("ai_asset_platform.execution.signal_order_bridge.SETTINGS", settings):
        result = execute_signal_via_ibkr_paper(
            service=service,
            ticker="AAPL",
            signal="BUY",
            shares=1,
            order_intent_id="disabled",
        )
    assert result.attempted is False
    service.execute_ibkr_paper_order.assert_not_called()


def test_non_actionable_signal_never_calls_execution_service() -> None:
    service = Mock()
    settings = PlatformSettings(enable_paper_trading=True, enable_ibkr_paper=True)
    with patch("ai_asset_platform.execution.signal_order_bridge.SETTINGS", settings):
        result = execute_signal_via_ibkr_paper(
            service=service,
            ticker="AAPL",
            signal="HOLD",
            shares=1,
            order_intent_id="hold",
        )
    assert result.attempted is False
    service.execute_ibkr_paper_order.assert_not_called()


def test_zero_shares_never_calls_execution_service() -> None:
    service = Mock()
    settings = PlatformSettings(enable_paper_trading=True, enable_ibkr_paper=True)
    with patch("ai_asset_platform.execution.signal_order_bridge.SETTINGS", settings):
        result = execute_signal_via_ibkr_paper(
            service=service,
            ticker="AAPL",
            signal="BUY",
            shares=0,
            order_intent_id="zero",
        )
    assert result.attempted is False
    service.execute_ibkr_paper_order.assert_not_called()


def test_enabled_buy_routes_once_to_execution_service() -> None:
    service = Mock()
    service.execute_ibkr_paper_order.return_value = object()
    settings = PlatformSettings(enable_paper_trading=True, enable_ibkr_paper=True)
    with patch("ai_asset_platform.execution.signal_order_bridge.SETTINGS", settings):
        result = execute_signal_via_ibkr_paper(
            service=service,
            ticker="AAPL",
            signal="BUY",
            shares=1,
            order_intent_id="signal-aapl-buy-1",
        )
    assert result.attempted is True
    service.execute_ibkr_paper_order.assert_called_once()
    order = service.execute_ibkr_paper_order.call_args.args[0]
    instrument = service.execute_ibkr_paper_order.call_args.kwargs["instrument"]
    assert order.symbol == "AAPL"
    assert order.side is OrderSide.BUY
    assert order.quantity == 1
    assert instrument.symbol == "AAPL"
    assert instrument.asset_class is AssetClass.STOCK
    assert instrument.exchange == "SMART"
    assert instrument.currency == "USD"
    assert instrument.verified_paper_test_quantity == 1
    assert service.execute_ibkr_paper_order.call_args.kwargs["order_intent_id"] == "signal-aapl-buy-1"


def test_enabled_sell_routes_once_to_execution_service() -> None:
    service = Mock()
    settings = PlatformSettings(enable_paper_trading=True, enable_ibkr_paper=True)
    with patch("ai_asset_platform.execution.signal_order_bridge.SETTINGS", settings):
        result = execute_signal_via_ibkr_paper(
            service=service,
            ticker="AAPL",
            signal="SELL",
            shares=1,
            order_intent_id="signal-aapl-sell-1",
        )
    assert result.attempted is True
    order = service.execute_ibkr_paper_order.call_args.args[0]
    assert order.side is OrderSide.SELL


def test_spy_is_explicit_verified_etf() -> None:
    instrument = _instrument_for_ticker("spy")
    assert instrument.symbol == "SPY"
    assert instrument.asset_class is AssetClass.ETF
    assert instrument.exchange == "SMART"
    assert instrument.currency == "USD"
    assert instrument.verified_paper_test_quantity == 1
    assert verified_paper_test_quantity_for_ticker("SPY") == 1


def test_tokyo_ticker_routes_numeric_symbol_tsej_jpy() -> None:
    service = Mock()
    service.execute_ibkr_paper_order.return_value = object()
    settings = PlatformSettings(enable_paper_trading=True, enable_ibkr_paper=True)
    with patch("ai_asset_platform.execution.signal_order_bridge.SETTINGS", settings):
        result = execute_signal_via_ibkr_paper(
            service=service,
            ticker="9432.T",
            signal="BUY",
            shares=100,
            order_intent_id="signal-9432-buy-100",
        )
    assert result.attempted is True
    order = service.execute_ibkr_paper_order.call_args.args[0]
    instrument = service.execute_ibkr_paper_order.call_args.kwargs["instrument"]
    assert order.symbol == "9432"
    assert instrument.symbol == "9432"
    assert instrument.exchange == "TSEJ"
    assert instrument.currency == "JPY"
    assert instrument.verified_paper_test_quantity == 100
    assert verified_paper_test_quantity_for_ticker("9432.T") == 100


def test_unverified_us_symbol_keeps_quantity_unverified() -> None:
    instrument = _instrument_for_ticker("MSFT")
    assert instrument.symbol == "MSFT"
    assert instrument.asset_class is AssetClass.STOCK
    assert instrument.exchange == "SMART"
    assert instrument.currency == "USD"
    assert instrument.verified_paper_test_quantity is None
    assert verified_paper_test_quantity_for_ticker("MSFT") is None


def test_unverified_tokyo_symbol_keeps_quantity_unverified() -> None:
    instrument = _instrument_for_ticker("7203.T")
    assert instrument.symbol == "7203"
    assert instrument.exchange == "TSEJ"
    assert instrument.currency == "JPY"
    assert instrument.verified_paper_test_quantity is None


def test_unknown_exchange_suffix_fails_closed() -> None:
    with pytest.raises(ValueError, match="not verified"):
        _instrument_for_ticker("VOD.L")
