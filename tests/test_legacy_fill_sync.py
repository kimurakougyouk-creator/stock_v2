import json

import pytest

from src.ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill


def test_records_confirmed_fill_in_legacy_shape(tmp_path):
    path = tmp_path / "paper_orders.jsonl"

    result = record_confirmed_fill(
        ticker="AAPL",
        side="BUY",
        filled_quantity=1.0,
        avg_fill_price=308.98,
        currency="USD",
        order_intent_id="intent-1",
        order_log_path=path,
    )

    assert result["mode"] == "IBKR_PAPER"
    assert result["ticker"] == "AAPL"
    assert result["side"] == "BUY"
    assert result["shares"] == 1
    assert result["reference_price"] == 308.98
    assert result["currency"] == "USD"
    assert result["status"] == "FILLED"
    assert json.loads(path.read_text(encoding="utf-8").strip()) == result


def test_same_intent_is_idempotent(tmp_path):
    path = tmp_path / "paper_orders.jsonl"
    kwargs = dict(
        ticker="AAPL",
        side="BUY",
        filled_quantity=1.0,
        avg_fill_price=308.98,
        currency="USD",
        order_intent_id="intent-1",
        order_log_path=path,
    )

    first = record_confirmed_fill(**kwargs)
    second = record_confirmed_fill(**kwargs)

    assert second == first
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_rejects_unconfirmed_or_invalid_fill_data(tmp_path):
    path = tmp_path / "paper_orders.jsonl"

    with pytest.raises(ValueError):
        record_confirmed_fill(
            ticker="AAPL",
            side="BUY",
            filled_quantity=0,
            avg_fill_price=308.98,
            currency="USD",
            order_intent_id="intent-1",
            order_log_path=path,
        )

    with pytest.raises(ValueError):
        record_confirmed_fill(
            ticker="AAPL",
            side="BUY",
            filled_quantity=1,
            avg_fill_price=0,
            currency="USD",
            order_intent_id="intent-2",
            order_log_path=path,
        )

    with pytest.raises(ValueError):
        record_confirmed_fill(
            ticker="AAPL",
            side="BUY",
            filled_quantity=1,
            avg_fill_price=308.98,
            currency="",
            order_intent_id="intent-3",
            order_log_path=path,
        )

    assert not path.exists()
