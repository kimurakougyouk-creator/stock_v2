import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import ai_asset_platform.brokers.ibkr_legacy_fill_retirement as module
from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrBrokerPosition,
    IbkrPaperAccountSnapshot,
)


def _settings():
    return SimpleNamespace(account_currency="JPY", account_timezone="Asia/Tokyo")


def _position(symbol: str, quantity: float) -> IbkrBrokerPosition:
    return IbkrBrokerPosition(
        symbol=symbol,
        sec_type="STK",
        currency="USD",
        exchange="NASDAQ",
        quantity=quantity,
        market_price=300.0,
        market_value=300.0 * quantity,
        average_cost=300.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
    )


def _account(*, positions=()) -> IbkrPaperAccountSnapshot:
    return IbkrPaperAccountSnapshot(
        connected=True,
        endpoint_port=4002,
        account_id="DU123",
        account_ready=True,
        base_currency="JPY",
        net_liquidation=1_000_000.0,
        available_funds=900_000.0,
        gross_position_value=100_000.0,
        total_cash_value=900_000.0,
        positions=tuple(positions),
        order_sent=False,
        errors=(),
    )


def _legacy_aapl(**overrides):
    row = {
        "created_at": "2026-08-21T07:22:13",
        "mode": "IBKR_PAPER",
        "ticker": "AAPL",
        "side": "BUY",
        "shares": 1,
        "reference_price": 312.2,
        "status": "FILLED",
        "order_intent_id": "signal-runner:AAPL:BUY:1:0.00000000",
    }
    row.update(overrides)
    return row


def _write(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _freeze_clock(monkeypatch):
    now = datetime(2026, 8, 24, 13, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    monkeypatch.setattr(module, "account_now", lambda settings: now)
    monkeypatch.setattr(module, "account_today", lambda settings: now.date())


def test_retires_stale_identityless_missing_currency_when_broker_is_flat(tmp_path, monkeypatch):
    _freeze_clock(monkeypatch)
    order_log = tmp_path / "results" / "paper_orders.jsonl"
    quarantine = tmp_path / "results" / "quarantine.jsonl"
    backups = tmp_path / "results" / "backups"
    safe = {
        "created_at": "2026-08-23T12:00:00+09:00",
        "mode": "IBKR_PAPER",
        "ticker": "SPY",
        "side": "SELL",
        "shares": 1,
        "reference_price": 765.0,
        "currency": "USD",
        "fx_to_account_rate": 158.0,
        "status": "FILLED",
        "order_intent_id": "closed-spy",
    }
    legacy = _legacy_aapl()
    _write(order_log, [safe, legacy])

    result = module.retire_stale_legacy_ibkr_fills(
        order_log_path=order_log,
        quarantine_path=quarantine,
        backup_dir=backups,
        settings=_settings(),
        account=_account(),
    )

    assert result.changed is True
    assert result.retired_count == 1
    assert result.retired_intent_ids == (legacy["order_intent_id"],)
    assert result.order_sent is False
    remaining = [json.loads(line) for line in order_log.read_text().splitlines()]
    assert remaining == [safe]
    quarantined = [json.loads(line) for line in quarantine.read_text().splitlines()]
    assert quarantined[0]["record"] == legacy
    assert quarantined[0]["reason"].startswith("stale incomplete")
    assert result.backup_path is not None
    assert result.backup_path.read_text(encoding="utf-8").count("\n") == 2


def test_broker_position_keeps_legacy_row_blocked(tmp_path, monkeypatch):
    _freeze_clock(monkeypatch)
    order_log = tmp_path / "paper_orders.jsonl"
    legacy = _legacy_aapl()
    _write(order_log, [legacy])

    with pytest.raises(module.LegacyFillRetirementError, match="broker-holds-1"):
        module.retire_stale_legacy_ibkr_fills(
            order_log_path=order_log,
            quarantine_path=tmp_path / "quarantine.jsonl",
            backup_dir=tmp_path / "backups",
            settings=_settings(),
            account=_account(positions=(_position("AAPL", 1.0),)),
        )

    assert json.loads(order_log.read_text()) == legacy


def test_current_day_record_cannot_be_retired(tmp_path, monkeypatch):
    _freeze_clock(monkeypatch)
    order_log = tmp_path / "paper_orders.jsonl"
    legacy = _legacy_aapl(created_at="2026-08-24T07:22:13+09:00")
    _write(order_log, [legacy])

    with pytest.raises(module.LegacyFillRetirementError, match="not-stale"):
        module.retire_stale_legacy_ibkr_fills(
            order_log_path=order_log,
            quarantine_path=tmp_path / "quarantine.jsonl",
            backup_dir=tmp_path / "backups",
            settings=_settings(),
            account=_account(),
        )


def test_recoverable_broker_identity_must_not_be_retired(tmp_path, monkeypatch):
    _freeze_clock(monkeypatch)
    order_log = tmp_path / "paper_orders.jsonl"
    legacy = _legacy_aapl(broker_exec_ids=["abc.1"])
    _write(order_log, [legacy])

    with pytest.raises(module.LegacyFillRetirementError, match="broker-exec-id-present"):
        module.retire_stale_legacy_ibkr_fills(
            order_log_path=order_log,
            quarantine_path=tmp_path / "quarantine.jsonl",
            backup_dir=tmp_path / "backups",
            settings=_settings(),
            account=_account(),
        )


def test_no_missing_evidence_is_noop(tmp_path, monkeypatch):
    _freeze_clock(monkeypatch)
    order_log = tmp_path / "paper_orders.jsonl"
    complete = _legacy_aapl(currency="USD", fx_to_account_rate=158.0)
    _write(order_log, [complete])

    result = module.retire_stale_legacy_ibkr_fills(
        order_log_path=order_log,
        quarantine_path=tmp_path / "quarantine.jsonl",
        backup_dir=tmp_path / "backups",
        settings=_settings(),
        account=_account(),
    )
    assert result.changed is False
    assert result.retired_count == 0
    assert result.order_sent is False


def test_unsafe_broker_snapshot_blocks_before_file_change(tmp_path, monkeypatch):
    _freeze_clock(monkeypatch)
    order_log = tmp_path / "paper_orders.jsonl"
    legacy = _legacy_aapl()
    _write(order_log, [legacy])
    unsafe = IbkrPaperAccountSnapshot(
        connected=False,
        endpoint_port=None,
        account_id=None,
        account_ready=False,
        base_currency=None,
        net_liquidation=None,
        available_funds=None,
        gross_position_value=None,
        total_cash_value=None,
    )

    with pytest.raises(module.LegacyFillRetirementError, match="not safe enough"):
        module.retire_stale_legacy_ibkr_fills(
            order_log_path=order_log,
            quarantine_path=tmp_path / "quarantine.jsonl",
            backup_dir=tmp_path / "backups",
            settings=_settings(),
            account=unsafe,
        )
    assert json.loads(order_log.read_text()) == legacy
