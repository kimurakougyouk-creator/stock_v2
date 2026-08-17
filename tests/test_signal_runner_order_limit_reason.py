from ai_asset_platform.execution.order_limit_reason import (
    detect_buy_order_limit_reason,
)


def test_signal_runner_reason_available_cash():
    result = detect_buy_order_limit_reason(
        requested_shares=100,
        affordable_shares=0,
        allocation_limit_shares=100,
        risk_limit_shares=100,
        portfolio_risk_limit_shares=100,
    )

    assert result is not None
    assert result.code == "AVAILABLE_CASH"
    assert result.message == "利用可能資金"


def test_signal_runner_reason_portfolio_risk():
    result = detect_buy_order_limit_reason(
        requested_shares=100,
        affordable_shares=100,
        allocation_limit_shares=100,
        risk_limit_shares=100,
        portfolio_risk_limit_shares=0,
    )

    assert result is not None
    assert result.code == "PORTFOLIO_RISK"
    assert result.message == "全保有ポジションの合計リスク上限"
