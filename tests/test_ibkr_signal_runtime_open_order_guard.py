from types import SimpleNamespace

import pytest

import ai_asset_platform.execution.ibkr_signal_runtime as module


def _pass_through_guards(monkeypatch, *, account_id="DU1234567"):
    monkeypatch.setattr(
        module,
        "SETTINGS",
        SimpleNamespace(enable_paper_trading=True, enable_ibkr_paper=True),
    )
    monkeypatch.setattr(module, "_exact_runtime_source_sha", lambda *args, **kwargs: "a" * 40)
    monkeypatch.setattr(module, "attest_strategy_source", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module,
        "evaluate_broker_position_guard",
        lambda **kwargs: SimpleNamespace(
            allowed=True,
            reason="broker/local positions reconciled",
            account=SimpleNamespace(account_id=account_id),
        ),
    )


def test_open_order_guard_blocks_before_broker_connection_when_order_already_open(monkeypatch):
    """A resting order from an earlier, separate connection/day is invisible
    to the position guard (no fill yet) -- this guard must catch it instead,
    and must do so before ever connecting the order-placing broker."""
    _pass_through_guards(monkeypatch)
    monkeypatch.setattr(
        module,
        "evaluate_open_order_guard",
        lambda **kwargs: SimpleNamespace(
            allowed=False,
            reason="an open order already exists at the broker for this symbol (order_id=[7])",
        ),
    )
    monkeypatch.setattr(
        module,
        "_connect_first_available_paper_broker",
        lambda **kwargs: pytest.fail("broker connection must not happen while an open order exists"),
    )

    result = module.execute_approved_signal_via_ibkr_paper(
        ticker="AAPL",
        signal="BUY",
        shares=1,
        order_intent_id="signal-runner:AAPL:BUY:1:bar2",
        process_start_source_sha="a" * 40,
        strategy_parameters_sha="b" * 64,
    )

    assert result.attempted is False
    assert "open order guard blocked" in result.reason
    assert "order_id=[7]" in result.reason


def test_open_order_guard_checks_the_instrument_symbol_not_the_ticker(monkeypatch):
    """9432.T maps to IBKR symbol 9432; the guard must be called with that
    broker symbol, not the raw ticker string, or a real resting order would
    never match."""
    _pass_through_guards(monkeypatch)
    captured = {}

    def _fake_guard(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(allowed=False, reason="an open order already exists at the broker for this symbol (order_id=[1])")

    monkeypatch.setattr(module, "evaluate_open_order_guard", _fake_guard)
    monkeypatch.setattr(
        module,
        "_connect_first_available_paper_broker",
        lambda **kwargs: pytest.fail("broker connection must not happen while an open order exists"),
    )

    module.execute_approved_signal_via_ibkr_paper(
        ticker="9432.T",
        signal="BUY",
        shares=100,
        order_intent_id="signal-runner:9432.T:BUY:100:bar3",
        process_start_source_sha="a" * 40,
        strategy_parameters_sha="b" * 64,
    )

    assert captured["ticker"] == "9432.T"
    assert captured["symbol"] == "9432"


def test_open_order_guard_is_bound_to_the_same_account_as_the_order_connection(monkeypatch):
    """Codex finding on PR #375: the open-order snapshot must be bound to the
    exact account the position guard verified, or Gateway/TWS exposing
    different accounts could let a duplicate order through."""
    _pass_through_guards(monkeypatch, account_id="DU9999999")
    captured = {}

    def _fake_guard(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(allowed=False, reason="an open order already exists at the broker for this symbol (order_id=[1])")

    monkeypatch.setattr(module, "evaluate_open_order_guard", _fake_guard)
    monkeypatch.setattr(
        module,
        "_connect_first_available_paper_broker",
        lambda **kwargs: pytest.fail("broker connection must not happen while an open order exists"),
    )

    module.execute_approved_signal_via_ibkr_paper(
        ticker="AAPL",
        signal="BUY",
        shares=1,
        order_intent_id="signal-runner:AAPL:BUY:1:bar5",
        process_start_source_sha="a" * 40,
        strategy_parameters_sha="b" * 64,
    )

    assert captured["expected_account_id"] == "DU9999999"


def test_open_order_guard_allows_broker_connection_when_no_open_order_exists(monkeypatch):
    _pass_through_guards(monkeypatch)
    monkeypatch.setattr(
        module,
        "evaluate_open_order_guard",
        lambda **kwargs: SimpleNamespace(allowed=True, reason="no open order exists at the broker for this symbol"),
    )
    reached_broker = []
    monkeypatch.setattr(
        module,
        "_connect_first_available_paper_broker",
        lambda **kwargs: reached_broker.append(kwargs) or (_ for _ in ()).throw(RuntimeError("stop here")),
    )

    with pytest.raises(RuntimeError, match="stop here"):
        module.execute_approved_signal_via_ibkr_paper(
            ticker="AAPL",
            signal="BUY",
            shares=1,
            order_intent_id="signal-runner:AAPL:BUY:1:bar4",
            process_start_source_sha="a" * 40,
            strategy_parameters_sha="b" * 64,
        )

    assert len(reached_broker) == 1
