import json
from pathlib import Path

import pytest

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrBrokerPosition,
    IbkrPaperAccountSnapshot,
)
from ai_asset_platform.brokers.ibkr_verified_derivative_ledger_cleanup import (
    VerifiedDerivativeLedgerCleanupError,
    quarantine_verified_derivative_rows,
)


ES_BUY_EXEC = "0000e1a7.6a8f948c.01.01"
ES_SELL_EXEC = "0000e1a7.6a8f948d.01.01"
SPY_OPTION_SELL_EXEC = "00020057.6a8c86b3.01.01"


def _account(*, positions=()):
    return IbkrPaperAccountSnapshot(
        connected=True,
        endpoint_port=4002,
        account_id="DU_TEST",
        account_ready=True,
        base_currency="JPY",
        net_liquidation=1_000_000.0,
        available_funds=900_000.0,
        gross_position_value=0.0,
        total_cash_value=900_000.0,
        positions=tuple(positions),
        order_sent=False,
        errors=(),
    )


def _position(symbol: str, sec_type: str, quantity: float):
    return IbkrBrokerPosition(
        symbol=symbol,
        sec_type=sec_type,
        currency="USD",
        exchange="CME" if sec_type == "FUT" else "SMART",
        quantity=quantity,
        market_price=1.0,
        market_value=1.0,
        average_cost=1.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
    )


def _row(*, ticker, side, price, order_id, exec_id):
    return {
        "created_at": "2026-08-24T00:00:00+09:00",
        "mode": "IBKR_PAPER",
        "ticker": ticker,
        "side": side,
        "shares": 1,
        "reference_price": price,
        "currency": "USD",
        "status": "FILLED",
        "order_intent_id": f"broker-recovery:{exec_id}",
        "broker_order_id": order_id,
        "broker_exec_ids": [exec_id],
    }


def _write(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_quarantines_only_exact_verified_derivatives_and_leaves_spy_stock_blocker(tmp_path: Path):
    ledger = tmp_path / "paper_orders.jsonl"
    quarantine = tmp_path / "quarantine.jsonl"
    backups = tmp_path / "backups"
    spy_stock_unknown = _row(
        ticker="SPY", side="BUY", price=765.45, order_id=3,
        exec_id="00012ec5.6ab91096.01.01",
    )
    rows = [
        spy_stock_unknown,
        _row(ticker="ES", side="BUY", price=7668.25, order_id=1, exec_id=ES_BUY_EXEC),
        _row(ticker="ES", side="SELL", price=7667.75, order_id=2, exec_id=ES_SELL_EXEC),
        _row(ticker="SPY", side="SELL", price=4.07, order_id=2, exec_id=SPY_OPTION_SELL_EXEC),
    ]
    _write(ledger, rows)

    result = quarantine_verified_derivative_rows(
        order_log_path=ledger,
        quarantine_path=quarantine,
        backup_dir=backups,
        account=_account(),
    )

    assert result.changed is True
    assert result.retired_count == 3
    assert result.order_sent is False
    active = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert active == [spy_stock_unknown]
    quarantined = [json.loads(line) for line in quarantine.read_text(encoding="utf-8").splitlines()]
    assert {row["record"]["broker_exec_ids"][0] for row in quarantined} == {
        ES_BUY_EXEC, ES_SELL_EXEC, SPY_OPTION_SELL_EXEC,
    }
    assert {row["verified_security_type"] for row in quarantined} == {"FUT", "OPT"}
    assert result.backup_path is not None
    assert result.backup_path.read_text(encoding="utf-8") == "".join(json.dumps(row) + "\n" for row in rows)


def test_current_matching_derivative_position_blocks_cleanup(tmp_path: Path):
    ledger = tmp_path / "paper_orders.jsonl"
    _write(ledger, [_row(ticker="ES", side="BUY", price=7668.25, order_id=1, exec_id=ES_BUY_EXEC)])
    with pytest.raises(VerifiedDerivativeLedgerCleanupError, match="still holds FUT ES"):
        quarantine_verified_derivative_rows(
            order_log_path=ledger,
            quarantine_path=tmp_path / "q.jsonl",
            backup_dir=tmp_path / "b",
            account=_account(positions=(_position("ES", "FUT", 1.0),)),
        )


def test_price_or_order_mismatch_is_not_quarantined(tmp_path: Path):
    ledger = tmp_path / "paper_orders.jsonl"
    row = _row(ticker="ES", side="BUY", price=9999.0, order_id=1, exec_id=ES_BUY_EXEC)
    _write(ledger, [row])
    result = quarantine_verified_derivative_rows(
        order_log_path=ledger,
        quarantine_path=tmp_path / "q.jsonl",
        backup_dir=tmp_path / "b",
        account=_account(),
    )
    assert result.changed is False
    assert json.loads(ledger.read_text(encoding="utf-8")) == row


def test_duplicate_verified_exec_id_blocks_without_mutation(tmp_path: Path):
    ledger = tmp_path / "paper_orders.jsonl"
    row = _row(ticker="ES", side="BUY", price=7668.25, order_id=1, exec_id=ES_BUY_EXEC)
    _write(ledger, [row, dict(row)])
    before = ledger.read_text(encoding="utf-8")
    with pytest.raises(VerifiedDerivativeLedgerCleanupError, match="duplicate active ledger row"):
        quarantine_verified_derivative_rows(
            order_log_path=ledger,
            quarantine_path=tmp_path / "q.jsonl",
            backup_dir=tmp_path / "b",
            account=_account(),
        )
    assert ledger.read_text(encoding="utf-8") == before
