import json
from pathlib import Path

import pytest

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrBrokerPosition,
    IbkrPaperAccountSnapshot,
)
from ai_asset_platform.brokers.ibkr_closed_spy_fx_ledger_repair import (
    ClosedSpyFxLedgerRepairError,
    repair_closed_spy_buy_fx,
)


BUY_EXEC = "00012ec5.6ab91096.01.01"
SELL_EXEC = "0000e511.6a8b602c.01.01"


def _account(*, quantity=0.0):
    positions = ()
    if quantity:
        positions = (
            IbkrBrokerPosition(
                symbol="SPY", sec_type="STK", currency="USD", exchange="ARCA",
                quantity=quantity, market_price=766.0, market_value=766.0,
                average_cost=765.45, unrealized_pnl=0.0, realized_pnl=0.0,
            ),
        )
    return IbkrPaperAccountSnapshot(
        connected=True, endpoint_port=4002, account_id="DU_TEST",
        account_ready=True, base_currency="JPY", net_liquidation=1_000_000.0,
        available_funds=900_000.0, gross_position_value=0.0,
        total_cash_value=900_000.0, positions=positions,
        order_sent=False, errors=(),
    )


def _buy():
    return {
        "created_at": "2026-08-21T16:33:06+09:00",
        "mode": "IBKR_PAPER", "status": "FILLED", "ticker": "SPY",
        "side": "BUY", "shares": 1, "reference_price": 765.45,
        "currency": "USD",
        "order_intent_id": f"broker-recovery:{BUY_EXEC}",
        "broker_order_id": 3, "broker_exec_ids": [BUY_EXEC],
    }


def _sell():
    return {
        "created_at": "2026-08-23T23:00:00+09:00",
        "mode": "IBKR_PAPER", "status": "FILLED", "ticker": "SPY",
        "side": "SELL", "shares": 1, "reference_price": 766.34,
        "currency": "USD",
        "order_intent_id": "overnight-paper-e2e:SPY:SELL:1:2026-08-23",
        "broker_order_id": 7, "broker_exec_ids": [SELL_EXEC],
        "fx_to_account_rate": 158.875,
    }


def _write(path: Path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_persists_exact_sell_fx_into_flat_matching_buy_with_backup(tmp_path):
    ledger = tmp_path / "paper_orders.jsonl"
    backups = tmp_path / "backups"
    rows = [_buy(), _sell()]
    _write(ledger, rows)
    before = ledger.read_text(encoding="utf-8")

    result = repair_closed_spy_buy_fx(
        order_log_path=ledger, backup_dir=backups, account=_account()
    )

    assert result.changed is True
    assert result.fx_to_account_rate == 158.875
    assert result.reference_exec_ids == (SELL_EXEC,)
    assert result.order_sent is False
    repaired = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert repaired[0]["fx_to_account_rate"] == 158.875
    assert repaired[0]["fx_accounting_source"] == "paired-close-sell-explicit-fx"
    assert repaired[0]["fx_accounting_reference_exec_ids"] == [SELL_EXEC]
    assert result.backup_path is not None
    assert result.backup_path.read_text(encoding="utf-8") == before


def test_broker_position_blocks_without_mutation(tmp_path):
    ledger = tmp_path / "paper_orders.jsonl"
    _write(ledger, [_buy(), _sell()])
    before = ledger.read_text(encoding="utf-8")
    with pytest.raises(ClosedSpyFxLedgerRepairError, match="broker SPY quantity"):
        repair_closed_spy_buy_fx(
            order_log_path=ledger,
            backup_dir=tmp_path / "backups",
            account=_account(quantity=1.0),
        )
    assert ledger.read_text(encoding="utf-8") == before


def test_overlapping_execution_identity_blocks_without_mutation(tmp_path):
    ledger = tmp_path / "paper_orders.jsonl"
    sell = _sell()
    sell["broker_exec_ids"] = [BUY_EXEC]
    _write(ledger, [_buy(), sell])
    before = ledger.read_text(encoding="utf-8")
    with pytest.raises(ClosedSpyFxLedgerRepairError, match="execution identity"):
        repair_closed_spy_buy_fx(
            order_log_path=ledger,
            backup_dir=tmp_path / "backups",
            account=_account(),
        )
    assert ledger.read_text(encoding="utf-8") == before


def test_already_repaired_ledger_is_idempotent(tmp_path):
    ledger = tmp_path / "paper_orders.jsonl"
    buy = _buy()
    buy["fx_to_account_rate"] = 158.875
    buy["fx_accounting_source"] = "paired-close-sell-explicit-fx"
    _write(ledger, [buy, _sell()])
    before = ledger.read_text(encoding="utf-8")

    result = repair_closed_spy_buy_fx(
        order_log_path=ledger,
        backup_dir=tmp_path / "backups",
        account=_account(),
    )

    assert result.changed is False
    assert result.backup_path is None
    assert ledger.read_text(encoding="utf-8") == before


def test_wrapper_is_local_repair_only_and_never_enables_orders():
    text = Path("ibkr_closed_spy_fx_ledger_repair_once.sh").read_text(encoding="utf-8")
    assert "ibkr_closed_spy_fx_ledger_repair_cli" in text
    assert "ibkr_reconciliation_evidence_audit" in text
    assert "bash ./ibkr_auto.sh" in text
    assert "AI_ASSET_ALLOW_CLOSED_SPY_FX_LEDGER_REPAIR=1" in text
    forbidden = (
        "AI_ASSET_ENABLE_IBKR_PAPER=1",
        "AI_ASSET_ENABLE_IBKR_PAPER=true",
        "AI_ASSET_ENABLE_LIVE_TRADING",
        "AI_ASSET_LIVE_TRADING_UNLOCKED",
        "placeOrder",
        "cancelOrder",
    )
    for marker in forbidden:
        assert marker not in text
