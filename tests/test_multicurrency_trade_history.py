from datetime import date

import pytest

from ai_asset_platform.reports.multicurrency_trade_history import (
    MulticurrencyTradeHistoryError,
    calculate_realized_trade_history,
    consecutive_losses_account_currency,
    realized_pnl_for_date,
)


def row(*, ticker="SPY", side, shares=1, price, currency="USD", fx=None, created_at="2026-08-22T10:00:00", intent=None, mode="IBKR_PAPER", status="FILLED"):
    payload = {
        "mode": mode,
        "status": status,
        "ticker": ticker,
        "side": side,
        "shares": shares,
        "reference_price": price,
        "currency": currency,
        "created_at": created_at,
        "order_intent_id": intent or f"{ticker}:{side}:{price}:{created_at}",
    }
    if fx is not None:
        payload["fx_to_account_rate"] = fx
    return payload


def test_cross_currency_buy_sell_realized_pnl_uses_each_fill_fx():
    records = [
        row(side="BUY", price=100, fx=150, intent="buy"),
        row(side="SELL", price=110, fx=151, intent="sell"),
    ]
    trades = calculate_realized_trade_history(records, account_currency="JPY")
    assert len(trades) == 1
    trade = trades[0]
    assert trade.average_cost_account == 15000.0
    assert trade.sell_unit_value_account == 16610.0
    assert trade.realized_pnl_account == 1610.0
    assert trade.account_currency == "JPY"
    assert trade.fill_currency == "USD"


def test_missing_cross_currency_fx_fails_closed():
    with pytest.raises(MulticurrencyTradeHistoryError, match="fx_to_account_rate"):
        calculate_realized_trade_history(
            [row(side="BUY", price=100, fx=None)],
            account_currency="JPY",
        )


def test_same_currency_uses_one_without_explicit_fx():
    records = [
        row(ticker="9432.T", side="BUY", shares=100, price=150, currency="JPY", fx=None, intent="buy"),
        row(ticker="9432.T", side="SELL", shares=100, price=160, currency="JPY", fx=None, intent="sell"),
    ]
    trades = calculate_realized_trade_history(records, account_currency="JPY")
    assert trades[0].realized_pnl_account == 1000.0


def test_duplicate_intent_is_not_double_counted():
    buy = row(side="BUY", price=100, fx=150, intent="buy")
    sell = row(side="SELL", price=110, fx=151, intent="sell")
    trades = calculate_realized_trade_history([buy, dict(buy), sell, dict(sell)], account_currency="JPY")
    assert len(trades) == 1
    assert trades[0].realized_pnl_account == 1610.0


def test_oversell_fails_closed():
    records = [
        row(side="BUY", shares=1, price=100, fx=150, intent="buy"),
        row(side="SELL", shares=2, price=110, fx=151, intent="sell"),
    ]
    with pytest.raises(MulticurrencyTradeHistoryError, match="exceeds"):
        calculate_realized_trade_history(records, account_currency="JPY")


def test_daily_realized_pnl_is_account_currency_value():
    records = [
        row(side="BUY", price=100, fx=150, intent="buy"),
        row(side="SELL", price=90, fx=150, intent="sell", created_at="2026-08-22T11:00:00"),
    ]
    assert realized_pnl_for_date(records, target_date=date(2026, 8, 22), account_currency="JPY") == -1500.0


def test_consecutive_losses_uses_converted_pnl():
    records = [
        row(side="BUY", price=100, fx=150, intent="b1"),
        row(side="SELL", price=90, fx=150, intent="s1"),
        row(side="BUY", price=100, fx=150, intent="b2", created_at="2026-08-22T12:00:00"),
        row(side="SELL", price=95, fx=150, intent="s2", created_at="2026-08-22T13:00:00"),
    ]
    assert consecutive_losses_account_currency(records, account_currency="JPY") == 2


def test_unconfirmed_ibkr_row_is_ignored():
    records = [row(side="BUY", price=100, fx=None, status="SENT")]
    assert calculate_realized_trade_history(records, account_currency="JPY") == []
