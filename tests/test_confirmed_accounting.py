import json

import pytest

from ai_asset_platform.reports.confirmed_accounting import (
    ConfirmedAccountingCurrencyError,
    audit_confirmed_accounting,
    audit_confirmed_accounting_file,
    confirmed_fill_records,
    load_confirmed_fill_records,
)


def fill(
    side,
    shares,
    price,
    *,
    status="FILLED",
    intent="x",
    ticker="AAPL",
    currency="JPY",
    mode="IBKR_PAPER",
):
    row = {
        "created_at": "2026-08-22T00:00:00",
        "mode": mode,
        "ticker": ticker,
        "side": side,
        "shares": shares,
        "reference_price": price,
        "status": status,
        "order_intent_id": intent,
    }
    if currency is not None:
        row["currency"] = currency
    return row


def test_only_explicit_filled_records_are_accounted():
    rows = [
        fill("BUY", 1, 100, status="READY", intent="ready"),
        fill("BUY", 1, 100, status="FILLED", intent="filled"),
        fill("BUY", 1, 100, status="REJECTED", intent="rejected"),
        {"ticker": "AAPL", "side": "BUY", "shares": 1, "reference_price": 100},
    ]
    confirmed = confirmed_fill_records(rows)
    assert [row["order_intent_id"] for row in confirmed] == ["filled"]


def test_accounting_rebuilds_realized_unrealized_equity_and_drawdown():
    rows = [
        fill("BUY", 2, 100, intent="buy"),
        fill("SELL", 1, 120, intent="sell"),
    ]
    result = audit_confirmed_accounting(rows, initial_capital=1000, account_currency="JPY")
    assert result.confirmed_fill_count == 2
    assert result.equity_point_count == 2
    assert result.ending_cash == 920
    assert result.ending_holdings == 120
    assert result.ending_equity == 1040
    assert result.realized_pnl == 20
    assert result.unrealized_pnl == 20
    assert result.maximum_drawdown == 0


def test_usd_ibkr_fill_cannot_be_mixed_into_jpy_accounting():
    with pytest.raises(ConfirmedAccountingCurrencyError, match="USD"):
        audit_confirmed_accounting(
            [fill("BUY", 1, 100, currency="USD")],
            initial_capital=1_000_000,
            account_currency="JPY",
        )


def test_ibkr_fill_missing_currency_fails_closed():
    with pytest.raises(ConfirmedAccountingCurrencyError, match="missing currency"):
        audit_confirmed_accounting(
            [fill("BUY", 1, 100, currency=None)],
            initial_capital=1_000_000,
            account_currency="JPY",
        )


def test_legacy_local_paper_row_without_currency_remains_backward_compatible():
    result = audit_confirmed_accounting(
        [fill("BUY", 1, 100, currency=None, mode="PAPER")],
        initial_capital=1000,
        account_currency="JPY",
    )
    assert result.confirmed_fill_count == 1
    assert result.ending_equity == 1000


def test_duplicate_confirmed_intent_is_not_double_accounted():
    item = fill("BUY", 1, 100, intent="same")
    result = audit_confirmed_accounting([item, dict(item)], initial_capital=1000)
    assert result.confirmed_fill_count == 2
    assert result.equity_point_count == 1
    assert result.ending_cash == 900
    assert result.ending_equity == 1000


def test_no_confirmed_evidence_keeps_initial_equity():
    result = audit_confirmed_accounting(
        [fill("BUY", 1, 100, status="SENT", intent="sent")],
        initial_capital=1000,
    )
    assert result.confirmed_fill_count == 0
    assert result.equity_point_count == 0
    assert result.ending_equity == 1000
    assert result.realized_pnl == 0
    assert result.maximum_drawdown == 0


def test_jsonl_loader_ignores_malformed_and_unconfirmed_lines(tmp_path):
    path = tmp_path / "paper_orders.jsonl"
    with path.open("w", encoding="utf-8") as file:
        file.write("not-json\n")
        file.write(json.dumps(fill("BUY", 1, 100, status="READY", intent="ready")) + "\n")
        file.write(json.dumps(fill("BUY", 1, 100, status="FILLED", intent="filled")) + "\n")
    loaded = load_confirmed_fill_records(path)
    assert len(loaded) == 1
    assert loaded[0]["order_intent_id"] == "filled"

    result = audit_confirmed_accounting_file(
        path,
        initial_capital=1000,
        account_currency="JPY",
    )
    assert result.confirmed_fill_count == 1
    assert result.ending_equity == 1000


def test_missing_log_fails_closed_as_no_confirmed_evidence(tmp_path):
    path = tmp_path / "missing.jsonl"
    assert load_confirmed_fill_records(path) == []
    result = audit_confirmed_accounting_file(path, initial_capital=500)
    assert result.confirmed_fill_count == 0
    assert result.ending_equity == 500
