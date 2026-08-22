from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import ai_asset_platform.brokers.ibkr_overnight_paper_e2e as module

ET = ZoneInfo("America/New_York")


def _settings(*, paper=True, ibkr=True, live=False, unlocked=False):
    return SimpleNamespace(
        enable_paper_trading=paper,
        enable_ibkr_paper=ibkr,
        enable_live_trading=live,
        live_trading_unlocked=unlocked,
    )


def _ready_whatif():
    return SimpleNamespace(
        ready=True,
        primary_exchange="ARCA",
        order_sent=False,
    )


def test_official_overnight_session_windows_are_dst_safe():
    assert module.is_ibkr_overnight_session_open(
        datetime(2026, 8, 23, 20, 0, tzinfo=ET)
    )
    assert module.is_ibkr_overnight_session_open(
        datetime(2026, 8, 24, 3, 49, tzinfo=ET)
    )
    assert not module.is_ibkr_overnight_session_open(
        datetime(2026, 8, 24, 3, 50, tzinfo=ET)
    )
    assert not module.is_ibkr_overnight_session_open(
        datetime(2026, 8, 22, 22, 0, tzinfo=ET)
    )
    assert not module.is_ibkr_overnight_session_open(
        datetime(2026, 8, 23, 12, 0, tzinfo=ET)
    )
    assert not module.is_ibkr_overnight_session_open(
        datetime(2026, 8, 21, 20, 0, tzinfo=ET)
    )


def test_session_key_is_stable_across_one_overnight_session():
    start = datetime(2026, 8, 23, 21, 0, tzinfo=ET)
    continuation = datetime(2026, 8, 24, 2, 0, tzinfo=ET)
    assert module.overnight_session_key(start) == "2026-08-23"
    assert module.overnight_session_key(continuation) == "2026-08-23"


def test_closed_session_stops_before_whatif_or_broker(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setenv("AI_ASSET_ENABLE_IBKR_OVERNIGHT_E2E", "true")
    calls = {"whatif": 0, "connect": 0}
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_overnight_order",
        lambda **kwargs: calls.__setitem__("whatif", calls["whatif"] + 1),
    )
    monkeypatch.setattr(
        module,
        "_connect_first_available_paper_broker",
        lambda: calls.__setitem__("connect", calls["connect"] + 1),
    )

    result = module.run_spy_overnight_paper_e2e(
        limit_price=700.0,
        now=datetime(2026, 8, 22, 22, 0, tzinfo=ET),
    )
    assert result.attempted is False
    assert calls == {"whatif": 0, "connect": 0}


def test_dedicated_opt_in_is_required_before_any_broker_request(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.delenv("AI_ASSET_ENABLE_IBKR_OVERNIGHT_E2E", raising=False)
    calls = {"whatif": 0}
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_overnight_order",
        lambda **kwargs: calls.__setitem__("whatif", calls["whatif"] + 1),
    )

    result = module.run_spy_overnight_paper_e2e(
        limit_price=700.0,
        now=datetime(2026, 8, 23, 21, 0, tzinfo=ET),
    )
    assert result.attempted is False
    assert calls["whatif"] == 0


def test_failed_whatif_never_reaches_actual_paper_order(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setenv("AI_ASSET_ENABLE_IBKR_OVERNIGHT_E2E", "true")
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_overnight_order",
        lambda **kwargs: SimpleNamespace(
            ready=False, primary_exchange=None, order_sent=False
        ),
    )
    calls = {"connect": 0}
    monkeypatch.setattr(
        module,
        "_connect_first_available_paper_broker",
        lambda: calls.__setitem__("connect", calls["connect"] + 1),
    )

    result = module.run_spy_overnight_paper_e2e(
        limit_price=700.0,
        now=datetime(2026, 8, 23, 21, 0, tzinfo=ET),
    )
    assert result.attempted is False
    assert calls["connect"] == 0


def test_ready_path_uses_limit_day_overnight_qty_one_and_persists_only_confirmed_fill(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setenv("AI_ASSET_ENABLE_IBKR_OVERNIGHT_E2E", "true")
    monkeypatch.setattr(
        module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _ready_whatif()
    )

    broker = SimpleNamespace(disconnect=lambda: None)
    monkeypatch.setattr(module, "_connect_first_available_paper_broker", lambda: broker)
    seen = {}
    broker_result = SimpleNamespace(order_id=9)

    class FakeExecutionService:
        def __init__(self, *, broker, account, risk_gate):
            seen["risk_gate"] = risk_gate

        def execute_ibkr_paper_order(
            self, order, *, order_intent_id, instrument, apply_account_fill
        ):
            seen["order"] = order
            seen["intent"] = order_intent_id
            seen["instrument"] = instrument
            seen["apply_account_fill"] = apply_account_fill
            return broker_result

    monkeypatch.setattr(module, "ExecutionService", FakeExecutionService)
    monkeypatch.setattr(module, "build_shared_risk_gate", lambda: "RISK_GATE")
    monkeypatch.setattr(
        module,
        "_confirmed_fill_from_broker_result",
        lambda result, expected: (1.0, 701.25),
    )
    persisted = []
    monkeypatch.setattr(
        module, "record_confirmed_fill", lambda **kwargs: persisted.append(kwargs)
    )

    result = module.run_spy_overnight_paper_e2e(
        limit_price=702.0,
        order_log_path=tmp_path / "paper_orders.jsonl",
        now=datetime(2026, 8, 23, 21, 0, tzinfo=ET),
    )

    assert result.attempted is True
    assert result.confirmed_fill_persisted is True
    assert seen["risk_gate"] == "RISK_GATE"
    assert seen["order"].symbol == "SPY"
    assert seen["order"].quantity == 1
    assert seen["order"].order_type.value == "LIMIT"
    assert seen["order"].limit_price == 702.0
    assert seen["instrument"].exchange == "OVERNIGHT"
    assert seen["instrument"].primary_exchange == "ARCA"
    assert seen["instrument"].verified_paper_test_quantity == 1
    assert seen["apply_account_fill"] is False
    assert seen["intent"] == "overnight-paper-e2e:SPY:BUY:1:2026-08-23"
    assert persisted[0]["filled_quantity"] == 1.0
    assert persisted[0]["avg_fill_price"] == 701.25


def test_same_session_different_limit_prices_keep_same_intent_id(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setenv("AI_ASSET_ENABLE_IBKR_OVERNIGHT_E2E", "true")
    monkeypatch.setattr(
        module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _ready_whatif()
    )
    broker = SimpleNamespace(disconnect=lambda: None)
    monkeypatch.setattr(module, "_connect_first_available_paper_broker", lambda: broker)
    intents = []

    class FakeExecutionService:
        def __init__(self, **kwargs):
            pass
        def execute_ibkr_paper_order(
            self, order, *, order_intent_id, instrument, apply_account_fill
        ):
            intents.append(order_intent_id)
            return SimpleNamespace(order_id=9)

    monkeypatch.setattr(module, "ExecutionService", FakeExecutionService)
    monkeypatch.setattr(module, "build_shared_risk_gate", lambda: None)
    monkeypatch.setattr(
        module, "_confirmed_fill_from_broker_result", lambda result, expected: None
    )

    now = datetime(2026, 8, 23, 21, 0, tzinfo=ET)
    module.run_spy_overnight_paper_e2e(limit_price=700.0, now=now)
    module.run_spy_overnight_paper_e2e(limit_price=705.0, now=now)
    assert intents == [
        "overnight-paper-e2e:SPY:BUY:1:2026-08-23",
        "overnight-paper-e2e:SPY:BUY:1:2026-08-23",
    ]


def test_unconfirmed_broker_result_is_never_persisted(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setenv("AI_ASSET_ENABLE_IBKR_OVERNIGHT_E2E", "true")
    monkeypatch.setattr(
        module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _ready_whatif()
    )
    broker = SimpleNamespace(disconnect=lambda: None)
    monkeypatch.setattr(module, "_connect_first_available_paper_broker", lambda: broker)

    class FakeExecutionService:
        def __init__(self, **kwargs):
            pass

        def execute_ibkr_paper_order(self, *args, **kwargs):
            return SimpleNamespace(order_id=9)

    monkeypatch.setattr(module, "ExecutionService", FakeExecutionService)
    monkeypatch.setattr(module, "build_shared_risk_gate", lambda: None)
    monkeypatch.setattr(
        module, "_confirmed_fill_from_broker_result", lambda result, expected: None
    )
    persisted = []
    monkeypatch.setattr(
        module, "record_confirmed_fill", lambda **kwargs: persisted.append(kwargs)
    )

    result = module.run_spy_overnight_paper_e2e(
        limit_price=702.0,
        now=datetime(2026, 8, 23, 21, 0, tzinfo=ET),
    )
    assert result.attempted is True
    assert result.confirmed_fill_persisted is False
    assert persisted == []
