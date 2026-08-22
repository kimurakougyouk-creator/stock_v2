from types import SimpleNamespace

import pytest

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.ibkr_contracts import build_ibkr_contract_spec, to_ibapi_contract
from ai_asset_platform.brokers.ibkr_overnight_audit import (
    _OvernightContractProbe,
    audit_ibkr_paper_overnight_contract,
)
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.core.asset_classes import AssetClass


def test_overnight_instrument_requires_primary_exchange():
    with pytest.raises(ValueError, match="primary_exchange"):
        InstrumentSpec("SPY", AssetClass.ETF, exchange="OVERNIGHT")


def test_overnight_contract_preserves_directed_routing_fields():
    instrument = InstrumentSpec(
        "SPY",
        AssetClass.ETF,
        exchange="OVERNIGHT",
        currency="USD",
        primary_exchange="ARCA",
    )
    spec = build_ibkr_contract_spec(instrument)
    assert spec.exchange == "OVERNIGHT"
    assert spec.primary_exchange == "ARCA"
    contract = to_ibapi_contract(spec)
    assert contract.exchange == "OVERNIGHT"
    assert contract.primaryExchange == "ARCA"


def test_blank_primary_exchange_is_rejected():
    with pytest.raises(ValueError, match="primary_exchange"):
        InstrumentSpec(
            "AAPL",
            AssetClass.STOCK,
            exchange="OVERNIGHT",
            primary_exchange=" ",
        )


def test_probe_tracks_contract_details_per_request():
    probe = _OvernightContractProbe()
    base = SimpleNamespace(contract=SimpleNamespace(symbol="SPY"))
    overnight = SimpleNamespace(contract=SimpleNamespace(symbol="SPY"))
    probe.contractDetails(1, base)
    probe.contractDetailsEnd(1)
    probe.contractDetails(2, overnight)
    probe.contractDetailsEnd(2)
    assert probe.details_by_req_id[1] == [base]
    assert probe.details_by_req_id[2] == [overnight]
    assert probe.done_by_req_id[1].is_set()
    assert probe.done_by_req_id[2].is_set()


def test_audit_never_sends_and_fails_closed_without_primary_exchange(monkeypatch):
    def fake_connect(self, host, port, client_id):
        self.connected_ready.set()

    def fake_request(self, req_id, contract, timeout):
        if req_id == 1:
            return [SimpleNamespace(contract=SimpleNamespace(symbol="SPY", primaryExchange=""))]
        raise AssertionError("overnight lookup must not run without primaryExchange")

    monkeypatch.setattr(_OvernightContractProbe, "connect", fake_connect)
    monkeypatch.setattr(_OvernightContractProbe, "run", lambda self: None)
    monkeypatch.setattr(_OvernightContractProbe, "request_contract_details", fake_request)
    monkeypatch.setattr(_OvernightContractProbe, "isConnected", lambda self: False)

    result = audit_ibkr_paper_overnight_contract(
        "SPY", config=IbkrConnectionConfig(port=7497), timeout=0.0
    )
    assert result.connected is True
    assert result.base_contract_resolved is True
    assert result.overnight_contract_ready is False
    assert result.order_sent is False


def test_audit_requires_broker_to_resolve_directed_overnight_contract(monkeypatch):
    seen = []

    def fake_connect(self, host, port, client_id):
        self.connected_ready.set()

    def fake_request(self, req_id, contract, timeout):
        seen.append((req_id, contract.exchange, getattr(contract, "primaryExchange", "")))
        if req_id == 1:
            return [SimpleNamespace(contract=SimpleNamespace(symbol="SPY", primaryExchange="ARCA"))]
        return []

    monkeypatch.setattr(_OvernightContractProbe, "connect", fake_connect)
    monkeypatch.setattr(_OvernightContractProbe, "run", lambda self: None)
    monkeypatch.setattr(_OvernightContractProbe, "request_contract_details", fake_request)
    monkeypatch.setattr(_OvernightContractProbe, "isConnected", lambda self: False)

    result = audit_ibkr_paper_overnight_contract(
        "SPY", config=IbkrConnectionConfig(port=7497), timeout=0.0
    )
    assert seen == [(1, "SMART", ""), (2, "OVERNIGHT", "ARCA")]
    assert result.base_contract_resolved is True
    assert result.overnight_contract_ready is False
    assert result.destination == "OVERNIGHT"
    assert result.order_sent is False


def test_audit_marks_ready_only_after_broker_resolves_overnight(monkeypatch):
    seen = []

    def fake_connect(self, host, port, client_id):
        self.connected_ready.set()

    def fake_request(self, req_id, contract, timeout):
        seen.append((req_id, contract.exchange, getattr(contract, "primaryExchange", "")))
        if req_id == 1:
            return [SimpleNamespace(contract=SimpleNamespace(symbol="SPY", primaryExchange="ARCA"))]
        return [SimpleNamespace(contract=SimpleNamespace(symbol="SPY", primaryExchange="ARCA"))]

    monkeypatch.setattr(_OvernightContractProbe, "connect", fake_connect)
    monkeypatch.setattr(_OvernightContractProbe, "run", lambda self: None)
    monkeypatch.setattr(_OvernightContractProbe, "request_contract_details", fake_request)
    monkeypatch.setattr(_OvernightContractProbe, "isConnected", lambda self: False)

    result = audit_ibkr_paper_overnight_contract(
        "SPY", config=IbkrConnectionConfig(port=7497), timeout=0.0
    )
    assert seen == [(1, "SMART", ""), (2, "OVERNIGHT", "ARCA")]
    assert result.connected is True
    assert result.base_contract_resolved is True
    assert result.overnight_contract_ready is True
    assert result.primary_exchange == "ARCA"
    assert result.destination == "OVERNIGHT"
    assert result.order_sent is False
