from ai_asset_platform.execution.order_limit_reason import (
    detect_buy_order_limit_reason,
)


def test_detect_available_cash_limit():
    result = detect_buy_order_limit_reason(
        requested_shares=100,
        affordable_shares=0,
        allocation_limit_shares=100,
        risk_limit_shares=100,
        portfolio_risk_limit_shares=100,
    )

    assert result is not None
    assert result.code == "AVAILABLE_CASH"
    assert result.limit_shares == 0


def test_detect_position_allocation_limit():
    result = detect_buy_order_limit_reason(
        requested_shares=100,
        affordable_shares=100,
        allocation_limit_shares=0,
        risk_limit_shares=100,
        portfolio_risk_limit_shares=100,
    )

    assert result is not None
    assert result.code == "POSITION_ALLOCATION"


def test_detect_trade_risk_limit():
    result = detect_buy_order_limit_reason(
        requested_shares=100,
        affordable_shares=100,
        allocation_limit_shares=100,
        risk_limit_shares=0,
        portfolio_risk_limit_shares=100,
    )

    assert result is not None
    assert result.code == "TRADE_RISK"


def test_detect_portfolio_risk_limit():
    result = detect_buy_order_limit_reason(
        requested_shares=100,
        affordable_shares=100,
        allocation_limit_shares=100,
        risk_limit_shares=100,
        portfolio_risk_limit_shares=0,
    )

    assert result is not None
    assert result.code == "PORTFOLIO_RISK"


def test_no_limit_reason_when_requested_quantity_is_allowed():
    result = detect_buy_order_limit_reason(
        requested_shares=100,
        affordable_shares=200,
        allocation_limit_shares=200,
        risk_limit_shares=200,
        portfolio_risk_limit_shares=200,
    )

    assert result is None
