from types import SimpleNamespace

from ai_asset_platform.brokers.ibkr_connection import IbkrConnectionResult
from ai_asset_platform.brokers.ibkr_etf_audit import (
    _ContractDetailsProbe,
    audit_ibkr_paper_etf,
)


def test_contract_details_probe_collects_and_finishes():
    probe = _ContractDetailsProbe()
    details = SimpleNamespace(contract=SimpleNamespace(symbol="SPY"))
    probe.contractDetails(1, details)
    probe.contractDetailsEnd(1)
    assert probe.details == [details]
    assert probe.ready.is_set()


def test_contract_details_probe_marks_fatal_contract_error():
    probe = _ContractDetailsProbe()
    probe.error(1, 0, 200, "No security definition")
    assert probe.fatal_error == "200: No security definition"
    assert probe.ready.is_set()


def test_etf_audit_stops_before_contract_lookup_when_connection_fails(monkeypatch):
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_etf_audit.probe_ibkr_paper_connection",
        lambda config, timeout: IbkrConnectionResult(False, None, "offline"),
    )
    result = audit_ibkr_paper_etf("spy")
    assert result.connected is False
    assert result.contract_resolved is False
    assert result.symbol == "SPY"
    assert result.order_sent is False
    assert result.message == "offline"
