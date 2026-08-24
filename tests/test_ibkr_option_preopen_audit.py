from types import SimpleNamespace

from ai_asset_platform.brokers import ibkr_option_preopen_audit as audit


def _settings(*, paper=True, live=False, unlocked=False):
    return SimpleNamespace(
        enable_ibkr_paper=paper,
        enable_live_trading=live,
        live_trading_unlocked=unlocked,
    )


def _candidate(**overrides):
    values = dict(
        con_id=audit.CON_ID,
        local_symbol=audit.LOCAL_SYMBOL,
        expiry=audit.EXPIRY,
        strike=audit.STRIKE,
        right=audit.RIGHT,
        multiplier=audit.MULTIPLIER,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _position(*, quantity=0.0, flat=True):
    return SimpleNamespace(
        connected=True,
        endpoint_port=4002,
        quantity=quantity,
        flat=flat,
        errors=(),
    )


def _snapshot(*, ready=True, executions=()):
    return SimpleNamespace(ready=ready, executions=tuple(executions), errors=())


def _prior(*, ready=False, pnl=None):
    return SimpleNamespace(ready=ready, realized_pnl_usd=pnl)


def _install_happy(monkeypatch, *, prior_ready=False):
    monkeypatch.setattr(audit, "SETTINGS", _settings())
    monkeypatch.setattr(audit, "_verified_target", lambda: (4002, _candidate(), ()))
    monkeypatch.setattr(audit, "probe_option_position", lambda timeout=15.0: _position())
    monkeypatch.setattr(audit, "_all_open_orders", lambda timeout=15.0: (True, 4002, 0, ()))
    monkeypatch.setattr(audit, "preview_ibkr_paper_execution_snapshot", lambda timeout=15.0: _snapshot())
    monkeypatch.setattr(
        audit,
        "run_option_postfill_audit",
        lambda wait_seconds=0.2: _prior(ready=prior_ready, pnl="10" if prior_ready else None),
    )


def test_happy_preopen_gate_is_ready_without_order(monkeypatch):
    _install_happy(monkeypatch)
    result = audit.run_option_preopen_audit(timeout=0.01)
    assert result.ready is True
    assert result.position_flat is True
    assert result.matching_open_order_count == 0
    assert result.execution_snapshot_ready is True
    assert result.real_order_sent is False
    assert result.live_order_sent is False


def test_prior_roundtrip_recovery_is_reported(monkeypatch):
    _install_happy(monkeypatch, prior_ready=True)
    result = audit.run_option_preopen_audit(timeout=0.01)
    assert result.ready is True
    assert result.prior_roundtrip_recovered is True
    assert result.prior_roundtrip_realized_pnl_usd == "10"
    assert "already recoverable" in result.reason


def test_matching_open_order_blocks_gate(monkeypatch):
    _install_happy(monkeypatch)
    monkeypatch.setattr(audit, "_all_open_orders", lambda timeout=15.0: (True, 4002, 1, ()))
    result = audit.run_option_preopen_audit(timeout=0.01)
    assert result.ready is False
    assert "open orders exist" in result.reason


def test_nonflat_position_blocks_gate(monkeypatch):
    _install_happy(monkeypatch)
    monkeypatch.setattr(audit, "probe_option_position", lambda timeout=15.0: _position(quantity=1.0, flat=False))
    result = audit.run_option_preopen_audit(timeout=0.01)
    assert result.ready is False
    assert "not flat" in result.reason


def test_contract_drift_blocks_gate(monkeypatch):
    _install_happy(monkeypatch)
    monkeypatch.setattr(audit, "_verified_target", lambda: (4002, _candidate(con_id=audit.CON_ID + 1), ()))
    result = audit.run_option_preopen_audit(timeout=0.01)
    assert result.ready is False
    assert "did not resolve" in result.reason


def test_live_unlock_blocks_before_broker_calls(monkeypatch):
    monkeypatch.setattr(audit, "SETTINGS", _settings(live=True, unlocked=True))
    monkeypatch.setattr(
        audit,
        "_verified_target",
        lambda: (_ for _ in ()).throw(AssertionError("broker must not be touched")),
    )
    result = audit.run_option_preopen_audit(timeout=0.01)
    assert result.ready is False
    assert "Live Trading safety lock" in result.reason
    assert result.real_order_sent is False
    assert result.live_order_sent is False
