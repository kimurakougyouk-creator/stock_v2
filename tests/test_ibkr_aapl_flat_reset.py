from ai_asset_platform.brokers.ibkr_aapl_flat_reset import (
    TARGET_LEGACY_INTENT,
    build_aapl_reset_plan,
)
from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrBrokerPosition,
    IbkrPaperAccountSnapshot,
)


def _snapshot(qty: float = 3.0, market_price: float = 300.0):
    return IbkrPaperAccountSnapshot(
        connected=True,
        endpoint_port=4002,
        account_id="DU_TEST",
        account_ready=True,
        base_currency="JPY",
        net_liquidation=1_000_000.0,
        available_funds=900_000.0,
        gross_position_value=100_000.0,
        total_cash_value=900_000.0,
        positions=(
            IbkrBrokerPosition(
                symbol="AAPL",
                sec_type="STK",
                currency="USD",
                exchange="NASDAQ",
                quantity=qty,
                market_price=market_price,
                market_value=qty * market_price,
                average_cost=313.5,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
            ),
        ),
        order_sent=False,
        errors=(),
    )


def _legacy():
    return {
        "created_at": "2026-08-21T07:22:13",
        "mode": "IBKR_PAPER",
        "order_intent_id": TARGET_LEGACY_INTENT,
        "reference_price": 312.2,
        "shares": 1,
        "side": "BUY",
        "status": "FILLED",
        "ticker": "AAPL",
    }


def test_plan_allows_only_verified_local1_broker3_mismatch():
    row = _legacy()
    plan = build_aapl_reset_plan(
        _snapshot(), raw_records=[row], accounting_records=[row]
    )
    assert plan.ready is True
    assert plan.broker_quantity == 3.0
    assert plan.local_quantity == 1.0
    assert plan.limit_price == 297.0


def test_plan_blocks_wrong_broker_quantity():
    row = _legacy()
    plan = build_aapl_reset_plan(
        _snapshot(qty=2.0), raw_records=[row], accounting_records=[row]
    )
    assert plan.ready is False
    assert "exactly 3" in plan.reason


def test_plan_blocks_if_exact_legacy_blocker_is_missing():
    row = _legacy()
    wrong = dict(row)
    wrong["currency"] = "USD"
    plan = build_aapl_reset_plan(
        _snapshot(), raw_records=[wrong], accounting_records=[row]
    )
    assert plan.ready is False
    assert "legacy blocker" in plan.reason


def test_plan_blocks_if_local_quantity_is_not_one():
    row = _legacy()
    second = dict(row)
    second["order_intent_id"] = "other-aapl-buy"
    plan = build_aapl_reset_plan(
        _snapshot(), raw_records=[row], accounting_records=[row, second]
    )
    assert plan.ready is False
    assert "local=1 / broker=3" in plan.reason


def test_plan_blocks_without_market_price():
    row = _legacy()
    plan = build_aapl_reset_plan(
        _snapshot(market_price=0.0), raw_records=[row], accounting_records=[row]
    )
    assert plan.ready is False
    assert "market price" in plan.reason
