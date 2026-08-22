from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_overnight_whatif as module
from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig


def test_readonly_contract_audit_retries_once_then_succeeds(monkeypatch):
    calls = []

    def fake_audit(symbol, config, timeout):
        calls.append((symbol, config.port, timeout))
        if len(calls) == 1:
            return SimpleNamespace(
                overnight_contract_ready=False,
                primary_exchange=None,
                message="502: temporary TWS connection failure",
            )
        return SimpleNamespace(
            overnight_contract_ready=True,
            primary_exchange="ARCA",
            message="ready",
        )

    monkeypatch.setattr(module, "audit_ibkr_paper_overnight_contract", fake_audit)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    result = module._resolve_overnight_contract_with_readonly_retry(
        "SPY",
        IbkrConnectionConfig(port=7497),
        timeout=0.0,
        attempts=2,
        retry_delay=0.0,
    )

    assert len(calls) == 2
    assert result.overnight_contract_ready is True
    assert result.primary_exchange == "ARCA"


def test_readonly_contract_audit_stops_after_configured_attempts(monkeypatch):
    calls = []

    def fake_audit(symbol, config, timeout):
        calls.append(symbol)
        return SimpleNamespace(
            overnight_contract_ready=False,
            primary_exchange=None,
            message="offline",
        )

    monkeypatch.setattr(module, "audit_ibkr_paper_overnight_contract", fake_audit)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    result = module._resolve_overnight_contract_with_readonly_retry(
        "SPY",
        IbkrConnectionConfig(port=7497),
        timeout=0.0,
        attempts=2,
        retry_delay=0.0,
    )

    assert len(calls) == 2
    assert result.overnight_contract_ready is False
