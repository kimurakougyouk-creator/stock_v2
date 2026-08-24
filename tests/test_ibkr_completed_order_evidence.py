from pathlib import Path

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrBrokerPosition,
    IbkrPaperAccountSnapshot,
)
from ai_asset_platform.brokers.ibkr_completed_order_evidence import (
    IbkrCompletedOrderEvidence,
    IbkrPaperCompletedOrderSnapshot,
    _aapl_next_action,
    audit_aapl_completed_order_evidence,
)


def _account(quantity: float) -> IbkrPaperAccountSnapshot:
    positions = ()
    if quantity:
        positions = (
            IbkrBrokerPosition(
                symbol="AAPL",
                sec_type="STK",
                currency="USD",
                exchange="NASDAQ",
                quantity=quantity,
                market_price=309.6,
                market_value=928.8,
                average_cost=313.50333335,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
            ),
        )
    return IbkrPaperAccountSnapshot(
        connected=True,
        endpoint_port=4002,
        account_id="PAPER",
        account_ready=True,
        base_currency="JPY",
        net_liquidation=1000000.0,
        available_funds=900000.0,
        gross_position_value=928.8,
        total_cash_value=900000.0,
        positions=positions,
        order_sent=False,
        errors=(),
    )


def _order(quantity: float, *, action: str = "BUY", order_id: int = 1) -> IbkrCompletedOrderEvidence:
    return IbkrCompletedOrderEvidence(
        order_id=order_id,
        perm_id=1000 + order_id,
        symbol="AAPL",
        sec_type="STK",
        currency="USD",
        exchange="NASDAQ",
        action=action,
        quantity=quantity,
        order_type="MKT",
        limit_price=None,
        status="Filled",
        completed_time="20260821 07:22:13 US/Eastern",
        completed_status="Filled",
        account="PAPER",
        order_ref="",
    )


def _snapshot(*orders: IbkrCompletedOrderEvidence) -> IbkrPaperCompletedOrderSnapshot:
    return IbkrPaperCompletedOrderSnapshot(
        connected=True,
        endpoint_port=4002,
        orders=tuple(orders),
        order_sent=False,
        errors=(),
    )


def test_no_completed_history_keeps_aapl_blocked():
    assert _aapl_next_action(
        broker_quantity=3.0,
        completed_buy_quantity=0.0,
        completed_count=0,
    ) == "AAPL_COMPLETED_ORDER_HISTORY_UNAVAILABLE_KEEP_BLOCKED"


def test_incomplete_completed_history_keeps_aapl_blocked():
    assert _aapl_next_action(
        broker_quantity=3.0,
        completed_buy_quantity=1.0,
        completed_count=1,
    ) == "AAPL_COMPLETED_ORDER_EVIDENCE_INCOMPLETE_KEEP_BLOCKED"


def test_sufficient_completed_buy_quantity_allows_review_not_auto_recovery():
    assert _aapl_next_action(
        broker_quantity=3.0,
        completed_buy_quantity=3.0,
        completed_count=2,
    ) == "REVIEW_AAPL_COMPLETED_ORDER_EVIDENCE_FOR_RECOVERY"


def test_flat_broker_position_is_reported_cleanly():
    assert _aapl_next_action(
        broker_quantity=0.0,
        completed_buy_quantity=0.0,
        completed_count=0,
    ) == "AAPL_BROKER_POSITION_IS_FLAT"


def test_audit_correlates_current_position_and_completed_orders_without_mutation():
    result = audit_aapl_completed_order_evidence(
        account=_account(3.0),
        completed_snapshot=_snapshot(_order(1.0, order_id=1), _order(2.0, order_id=2)),
    )
    assert result.account_ready is True
    assert result.completed_orders_ready is True
    assert result.endpoint_port == 4002
    assert result.broker_quantity == 3.0
    assert result.aapl_completed_buy_quantity == 3.0
    assert len(result.aapl_completed_orders) == 2
    assert result.next_action == "REVIEW_AAPL_COMPLETED_ORDER_EVIDENCE_FOR_RECOVERY"
    assert result.order_sent is False
    assert result.ledger_changed is False


def test_sell_completed_order_does_not_count_as_buy_quantity():
    result = audit_aapl_completed_order_evidence(
        account=_account(3.0),
        completed_snapshot=_snapshot(_order(1.0), _order(1.0, action="SELL", order_id=2)),
    )
    assert result.aapl_completed_buy_quantity == 1.0
    assert result.next_action == "AAPL_COMPLETED_ORDER_EVIDENCE_INCOMPLETE_KEEP_BLOCKED"


def test_module_contains_no_order_transmission_or_ledger_write_path():
    source = Path("src/ai_asset_platform/brokers/ibkr_completed_order_evidence.py").read_text(encoding="utf-8")
    assert ".placeOrder(" not in source
    assert ".cancelOrder(" not in source
    assert "record_confirmed_fill" not in source
    assert "write_text(" not in source
    assert "open(\"a\"" not in source
    assert "reqCompletedOrders(False)" in source
