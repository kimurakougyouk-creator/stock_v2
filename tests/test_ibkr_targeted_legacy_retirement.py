import json
from pathlib import Path

import pytest

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrBrokerPosition,
    IbkrPaperAccountSnapshot,
)
from ai_asset_platform.brokers.ibkr_legacy_fill_retirement import LegacyFillRetirementError
from ai_asset_platform.brokers.ibkr_targeted_legacy_retirement import (
    retire_stale_legacy_ibkr_fill_by_intent,
)

TARGET = "signal-runner:AAPL:BUY:1:0.00000000"


def _account(*, aapl_qty: float = 0.0):
    positions = ()
    if aapl_qty:
        positions = (
            IbkrBrokerPosition(
                symbol="AAPL", sec_type="STK", currency="USD", exchange="NASDAQ",
                quantity=aapl_qty, market_price=300.0, market_value=900.0,
                average_cost=313.5, unrealized_pnl=0.0, realized_pnl=0.0,
            ),
        )
    return IbkrPaperAccountSnapshot(
        connected=True, endpoint_port=4002, account_id="DU_TEST", account_ready=True,
        base_currency="JPY", net_liquidation=1_000_000.0,
        available_funds=900_000.0, gross_position_value=0.0,
        total_cash_value=900_000.0, positions=positions, order_sent=False, errors=(),
    )


def _aapl_row():
    return {
        "created_at": "2020-01-01T00:00:00",
        "mode": "IBKR_PAPER",
        "order_intent_id": TARGET,
        "reference_price": 312.2,
        "shares": 1,
        "side": "BUY",
        "status": "FILLED",
        "ticker": "AAPL",
    }


def _spy_blocker():
    return {
        "created_at": "2020-01-01T00:00:00",
        "mode": "IBKR_PAPER",
        "order_intent_id": "broker-recovery:spy",
        "reference_price": 765.45,
        "shares": 1,
        "side": "BUY",
        "status": "FILLED",
        "ticker": "SPY",
        "currency": "USD",
        "broker_order_id": 3,
        "broker_exec_ids": ["spy-exec"],
    }


def test_targeted_retirement_removes_only_target_and_preserves_unrelated_blocker(tmp_path: Path):
    ledger = tmp_path / "paper_orders.jsonl"
    quarantine = tmp_path / "quarantine.jsonl"
    backup_dir = tmp_path / "backups"
    rows = [_aapl_row(), _spy_blocker()]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    result = retire_stale_legacy_ibkr_fill_by_intent(
        TARGET,
        order_log_path=ledger,
        quarantine_path=quarantine,
        backup_dir=backup_dir,
        account=_account(aapl_qty=0.0),
    )
    assert result.changed is True
    active = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert [row["ticker"] for row in active] == ["SPY"]
    quarantined = [json.loads(line) for line in quarantine.read_text(encoding="utf-8").splitlines()]
    assert quarantined[0]["record"]["order_intent_id"] == TARGET
    assert result.backup_path is not None and result.backup_path.exists()


def test_targeted_retirement_blocks_when_broker_still_holds_aapl(tmp_path: Path):
    ledger = tmp_path / "paper_orders.jsonl"
    ledger.write_text(json.dumps(_aapl_row()) + "\n", encoding="utf-8")
    with pytest.raises(LegacyFillRetirementError, match="broker-flat"):
        retire_stale_legacy_ibkr_fill_by_intent(
            TARGET,
            order_log_path=ledger,
            quarantine_path=tmp_path / "q.jsonl",
            backup_dir=tmp_path / "b",
            account=_account(aapl_qty=3.0),
        )
