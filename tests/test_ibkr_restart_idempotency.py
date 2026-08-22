import json

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill


def test_confirmed_fill_is_idempotent_after_process_restart(tmp_path):
    """Persistent order_intent_id prevents duplicate accounting after restart."""
    log_path = tmp_path / "paper_orders.jsonl"
    intent = "restart-e2e:AAPL:BUY:1"

    first = record_confirmed_fill(
        ticker="AAPL",
        side="BUY",
        filled_quantity=1,
        avg_fill_price=312.20,
        currency="USD",
        order_intent_id=intent,
        order_log_path=log_path,
    )
    second = record_confirmed_fill(
        ticker="AAPL",
        side="BUY",
        filled_quantity=1,
        avg_fill_price=312.20,
        currency="USD",
        order_intent_id=intent,
        order_log_path=log_path,
    )

    assert second == first
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["order_intent_id"] == intent
    assert records[0]["currency"] == "USD"


def test_sent_intent_lock_survives_new_adapter_and_blocks_resend(monkeypatch, tmp_path):
    """A durable intent lock blocks a second adapter/process from resending."""
    lock_dir = tmp_path / "locks"
    intent = "restart-e2e:AAPL:BUY:1"
    order = OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)

    safe_name = "restart-e2e_AAPL_BUY_1.lock"
    lock_dir.mkdir(parents=True)
    (lock_dir / safe_name).write_text('{"pid": 123, "acquired_at": 1.0}', encoding="utf-8")

    broker = IbkrBrokerAdapter(
        config=create_ibkr_paper_config(use_gateway=True),
        enable_paper_order_transmission=True,
        fill_state_path=tmp_path / "fill_state.json",
    )

    result = broker.place_order_and_await_fill(
        order,
        order_intent_id=intent,
        intent_lock_dir=lock_dir,
        timeout_seconds=0.01,
    )

    assert result.status == "DUPLICATE_BLOCKED"
    assert result.sent is False
    assert result.order_id is None


def test_unconfirmed_fill_is_never_persisted(tmp_path):
    """Recovery must fail closed when fill evidence is invalid."""
    log_path = tmp_path / "paper_orders.jsonl"
    try:
        record_confirmed_fill(
            ticker="AAPL",
            side="BUY",
            filled_quantity=0,
            avg_fill_price=312.20,
            currency="USD",
            order_intent_id="invalid-fill",
            order_log_path=log_path,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("zero-quantity fill must be rejected")

    assert not log_path.exists()
