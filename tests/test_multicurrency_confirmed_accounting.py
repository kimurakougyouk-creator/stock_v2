import pytest

from ai_asset_platform.reports.multicurrency_confirmed_accounting import (
    MulticurrencyConfirmedAccountingError,
    audit_multicurrency_confirmed_accounting,
    calculate_multicurrency_equity_curve,
)


def fill(
    side,
    shares,
    price,
    *,
    ticker="SPY",
    currency="USD",
    fx=150.0,
    intent="x",
    status="FILLED",
):
    row = {
        "created_at": "2026-08-22T00:00:00",
        "mode": "IBKR_PAPER",
        "ticker": ticker,
        "side": side,
        "shares": shares,
        "reference_price": price,
        "currency": currency,
        "status": status,
        "order_intent_id": intent,
    }
    if fx is not None:
        row["fx_to_account_rate"] = fx
    return row


def test_cross_currency_buy_requires_explicit_per_fill_fx():
    row = fill("BUY", 1, 100, fx=None)
    with pytest.raises(MulticurrencyConfirmedAccountingError, match="explicit"):
        audit_multicurrency_confirmed_accounting([row], initial_capital=100_000)


def test_usd_buy_is_converted_into_jpy_account_currency():
    result = audit_multicurrency_confirmed_accounting(
        [fill("BUY", 1, 100, fx=150.0)],
        initial_capital=100_000,
        account_currency="JPY",
    )
    assert result.ending_cash == 85_000
    assert result.ending_holdings == 15_000
    assert result.ending_equity == 100_000
    assert result.unrealized_pnl == 0


def test_realized_pnl_uses_explicit_fx_at_each_fill():
    rows = [
        fill("BUY", 1, 100, fx=150.0, intent="buy"),
        fill("SELL", 1, 110, fx=151.0, intent="sell"),
    ]
    result = audit_multicurrency_confirmed_accounting(
        rows,
        initial_capital=100_000,
        account_currency="JPY",
    )
    assert result.ending_cash == 101_610
    assert result.ending_holdings == 0
    assert result.ending_equity == 101_610
    assert result.realized_pnl == 1_610


def test_open_usd_position_revalues_when_new_explicit_usd_rate_arrives():
    rows = [
        fill("BUY", 1, 100, ticker="SPY", fx=150.0, intent="spy"),
        fill("BUY", 1, 200, ticker="AAPL", fx=151.0, intent="aapl"),
    ]
    points = calculate_multicurrency_equity_curve(
        rows,
        initial_capital=100_000,
        account_currency="JPY",
    )
    assert points[0].holdings == 15_000
    assert points[1].holdings == 45_300
    assert points[1].unrealized_pnl == 100


def test_same_currency_rejects_non_one_fx_rate():
    row = fill("BUY", 100, 150, ticker="9432.T", currency="JPY", fx=150.0)
    with pytest.raises(MulticurrencyConfirmedAccountingError, match="same-currency"):
        audit_multicurrency_confirmed_accounting([row], initial_capital=1_000_000)


def test_same_currency_can_omit_fx_rate():
    row = fill("BUY", 100, 150, ticker="9432.T", currency="JPY", fx=None)
    result = audit_multicurrency_confirmed_accounting([row], initial_capital=1_000_000)
    assert result.ending_cash == 985_000
    assert result.ending_holdings == 15_000
    assert result.ending_equity == 1_000_000


def test_duplicate_intent_is_not_double_accounted():
    row = fill("BUY", 1, 100, fx=150.0, intent="same")
    result = audit_multicurrency_confirmed_accounting(
        [row, dict(row)], initial_capital=100_000
    )
    assert result.confirmed_fill_count == 1
    assert result.ending_cash == 85_000


def test_unconfirmed_rows_are_ignored():
    result = audit_multicurrency_confirmed_accounting(
        [fill("BUY", 1, 100, status="SENT")], initial_capital=100_000
    )
    assert result.confirmed_fill_count == 0
    assert result.ending_equity == 100_000


def test_ibkr_fill_missing_currency_fails_closed():
    row = fill("BUY", 1, 100)
    row.pop("currency")
    with pytest.raises(MulticurrencyConfirmedAccountingError, match="missing currency"):
        audit_multicurrency_confirmed_accounting([row], initial_capital=100_000)


def test_sell_cannot_exceed_accounted_holdings():
    rows = [
        fill("BUY", 1, 100, fx=150.0, intent="buy"),
        fill("SELL", 2, 110, fx=151.0, intent="sell"),
    ]
    with pytest.raises(MulticurrencyConfirmedAccountingError, match="exceeds"):
        audit_multicurrency_confirmed_accounting(rows, initial_capital=100_000)
