from dataclasses import replace
from datetime import date

import pytest

from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.verified_paper_preflight import (
    VerifiedPaperPreflightError,
    evaluate_verified_paper_preflight,
)


def fill(*, ticker, side, shares, price, currency, fx=None, intent=None, created_at="2026-08-22T10:00:00"):
    row = {
        "mode": "IBKR_PAPER",
        "status": "FILLED",
        "ticker": ticker,
        "side": side,
        "shares": shares,
        "reference_price": price,
        "currency": currency,
        "order_intent_id": intent or f"{ticker}:{side}:{price}:{created_at}",
        "created_at": created_at,
    }
    if fx is not None:
        row["fx_to_account_rate"] = fx
    return row


def settings(**overrides):
    return replace(
        SETTINGS,
        account_currency="JPY",
        max_positions=5,
        max_position_allocation=0.20,
        max_portfolio_allocation=0.80,
        max_portfolio_risk_rate=0.03,
        max_daily_trading_amount_yen=1_000_000.0,
        **overrides,
    )


def test_usd_buy_uses_explicit_jpy_rate_and_passes_small_pilot():
    result = evaluate_verified_paper_preflight(
        records=[], ticker="SPY", side="BUY", quantity=1, reference_price=700,
        instrument_currency="USD", settings=settings(), initial_capital=1_000_000,
        fx_to_account_rate=150, stop_loss_rate=0.03,
        target_date=date(2026, 8, 22),
    )
    assert result.allowed is True
    assert result.planned_notional_account == 105000.0
    assert result.fx_to_account_rate == 150.0


def test_cross_currency_buy_without_fx_fails_closed():
    with pytest.raises(VerifiedPaperPreflightError, match="explicit FX"):
        evaluate_verified_paper_preflight(
            records=[], ticker="SPY", side="BUY", quantity=1, reference_price=700,
            instrument_currency="USD", settings=settings(), initial_capital=1_000_000,
            fx_to_account_rate=None, stop_loss_rate=0.03,
        )


def test_existing_position_blocks_new_buy():
    records = [fill(ticker="SPY", side="BUY", shares=1, price=700, currency="USD", fx=150, intent="buy")]
    result = evaluate_verified_paper_preflight(
        records=records, ticker="SPY", side="BUY", quantity=1, reference_price=710,
        instrument_currency="USD", settings=settings(), initial_capital=1_000_000,
        fx_to_account_rate=150, stop_loss_rate=0.03,
        target_date=date(2026, 8, 22),
    )
    assert result.allowed is False
    assert "already held" in result.reason


def test_protective_sell_is_not_blocked_by_buy_allocation_limits():
    records = [fill(ticker="SPY", side="BUY", shares=1, price=700, currency="USD", fx=150, intent="buy")]
    result = evaluate_verified_paper_preflight(
        records=records, ticker="SPY", side="SELL", quantity=1, reference_price=690,
        instrument_currency="USD", settings=settings(max_position_allocation=0.01, max_portfolio_allocation=0.01),
        initial_capital=1_000_000, fx_to_account_rate=150, stop_loss_rate=0.03,
        target_date=date(2026, 8, 22),
    )
    assert result.allowed is True


def test_sell_over_confirmed_position_fails_closed():
    records = [fill(ticker="SPY", side="BUY", shares=1, price=700, currency="USD", fx=150, intent="buy")]
    result = evaluate_verified_paper_preflight(
        records=records, ticker="SPY", side="SELL", quantity=2, reference_price=690,
        instrument_currency="USD", settings=settings(), initial_capital=1_000_000,
        fx_to_account_rate=150, stop_loss_rate=0.03,
        target_date=date(2026, 8, 22),
    )
    assert result.allowed is False
    assert "exceeds" in result.reason


def test_position_allocation_blocks_oversized_buy():
    result = evaluate_verified_paper_preflight(
        records=[], ticker="SPY", side="BUY", quantity=2, reference_price=700,
        instrument_currency="USD", settings=settings(), initial_capital=1_000_000,
        fx_to_account_rate=150, stop_loss_rate=0.03,
        target_date=date(2026, 8, 22),
    )
    assert result.allowed is False
    assert "position allocation" in result.reason


def test_daily_trading_amount_is_converted_before_limit_check():
    records = [fill(ticker="AAPL", side="BUY", shares=1, price=300, currency="USD", fx=150, intent="aapl")]
    result = evaluate_verified_paper_preflight(
        records=records, ticker="SPY", side="BUY", quantity=1, reference_price=700,
        instrument_currency="USD",
        settings=settings(max_daily_trading_amount_yen=140_000.0),
        initial_capital=1_000_000, fx_to_account_rate=150, stop_loss_rate=0.03,
        target_date=date(2026, 8, 22),
    )
    assert result.allowed is False
    assert result.daily_trading_amount_account == 45000.0
    assert "daily trading amount" in result.reason


def test_old_cross_currency_record_without_fx_makes_new_exposure_fail_closed():
    records = [fill(ticker="AAPL", side="BUY", shares=1, price=300, currency="USD", fx=None, intent="old")]
    with pytest.raises(VerifiedPaperPreflightError, match="fx_to_account_rate"):
        evaluate_verified_paper_preflight(
            records=records, ticker="SPY", side="BUY", quantity=1, reference_price=700,
            instrument_currency="USD", settings=settings(), initial_capital=1_000_000,
            fx_to_account_rate=150, stop_loss_rate=0.03,
        )


def test_same_currency_jpy_pilot_needs_no_fx_snapshot_value():
    result = evaluate_verified_paper_preflight(
        records=[], ticker="9432.T", side="BUY", quantity=100, reference_price=150,
        instrument_currency="JPY", settings=settings(), initial_capital=1_000_000,
        fx_to_account_rate=None, stop_loss_rate=0.03,
        target_date=date(2026, 8, 22),
    )
    assert result.allowed is True
    assert result.fx_to_account_rate == 1.0
