from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from pathlib import Path

import ai_asset_platform.brokers.ibkr_9432_flat_close as module
from ai_asset_platform.brokers.ibkr_global_stock_discovery import IbkrGlobalStockCandidate


def _candidate(**kwargs):
    values = dict(
        symbol="9432",
        local_symbol="9432",
        exchange="TSEJ",
        primary_exchange="TSEJ",
        currency="JPY",
        con_id=270132,
        min_tick=0.1,
        min_size=100.0,
        size_increment=100.0,
        suggested_size_increment=100.0,
        valid_exchanges="TSEJ",
        order_types="MKT,LMT",
        time_zone_id="Japan",
        trading_hours="20260824:0900-1530",
        liquid_hours="20260824:0900-1530",
    )
    values.update(kwargs)
    return IbkrGlobalStockCandidate(**values)


def _snapshot(qty=100.0, market_price=166.84):
    position = SimpleNamespace(symbol="9432", sec_type="STK", quantity=qty, market_price=market_price)
    return SimpleNamespace(
        ready=True,
        order_sent=False,
        base_currency="JPY",
        endpoint_port=4002,
        positions=(position,),
    )


def _records():
    return [{
        "status": "FILLED",
        "ticker": "9432",
        "side": "BUY",
        "shares": 100,
        "currency": "JPY",
        "broker_order_id": 6,
        "broker_exec_ids": [module.KNOWN_BUY_EXEC_ID],
        "order_intent_id": "broker-recovery:" + module.KNOWN_BUY_EXEC_ID,
    }]


def test_liquid_session_gate_uses_broker_hours_and_timezone():
    candidate = _candidate()
    assert module.liquid_session_is_open(
        candidate,
        now=datetime(2026, 8, 24, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
    ) is True
    assert module.liquid_session_is_open(
        candidate,
        now=datetime(2026, 8, 24, 16, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
    ) is False


def test_close_plan_requires_exact_reconciled_controlled_position(monkeypatch):
    monkeypatch.setattr(
        module,
        "evaluate_broker_position_guard",
        lambda **kwargs: SimpleNamespace(allowed=True, local_quantity=100.0, reason="broker/local positions reconciled"),
    )
    discovery = SimpleNamespace(resolved=True, order_sent=False, candidates=(_candidate(),))
    result = module.build_9432_close_plan(
        _snapshot(),
        accounting_records=_records(),
        discovery=discovery,
        now=datetime(2026, 8, 24, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    assert result.ready is True
    assert result.broker_quantity == 100.0
    assert result.local_quantity == 100.0
    assert result.limit_price == 165.1


def test_close_plan_fails_closed_if_lot_or_position_changes(monkeypatch):
    monkeypatch.setattr(
        module,
        "evaluate_broker_position_guard",
        lambda **kwargs: SimpleNamespace(allowed=True, local_quantity=100.0, reason="ok"),
    )
    discovery = SimpleNamespace(resolved=True, order_sent=False, candidates=(_candidate(min_size=1.0),))
    result = module.build_9432_close_plan(
        _snapshot(),
        accounting_records=_records(),
        discovery=discovery,
        now=datetime(2026, 8, 24, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    assert result.ready is False
    assert "contract/lot" in result.reason

    result = module.build_9432_close_plan(
        _snapshot(qty=99.0),
        accounting_records=_records(),
        discovery=SimpleNamespace(resolved=True, order_sent=False, candidates=(_candidate(),)),
        now=datetime(2026, 8, 24, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    assert result.ready is False
    assert "exactly 100" in result.reason


def test_known_buy_evidence_is_exact_and_identity_based():
    assert module._known_buy_is_trusted(_records()) is True
    changed = _records()
    changed[0]["broker_exec_ids"] = ["wrong"]
    assert module._known_buy_is_trusted(changed) is False


def test_wrapper_scopes_paper_opt_in_after_pytest_and_never_enables_live():
    text = Path("ibkr_9432_flat_close_once.sh").read_text(encoding="utf-8")
    pytest_index = text.index("python -m pytest -q")
    paper_index = text.index("AI_ASSET_ENABLE_IBKR_PAPER=1")
    close_index = text.index("python -m ai_asset_platform.brokers.ibkr_9432_flat_close")
    assert pytest_index < paper_index < close_index
    assert "YES_SELL_EXACTLY_100_9432_TSEJ_PAPER_TO_FLAT" in text
    assert "AI_ASSET_ENABLE_LIVE_TRADING=1" not in text
    assert "AI_ASSET_LIVE_TRADING_UNLOCKED=1" not in text
