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


def test_probe_collects_contract_details():
    probe = _OvernightContractProbe()
    details = SimpleNamespace(contract=SimpleNamespace(symbol="SPY"))
    probe.contractDetails(1, details)
    probe.contractDetailsEnd(1)
    assert probe.details == [details]
    assert probe.ready.is_set()


def test_audit_never_sends_and_fails_closed_without_primary_exchange(monkeypatch):
    def fake_connect(self, host, port, client_id):
        self.connected_ready.set()

    def fake_req_contract_details(self, req_id, contract):
        self.details.append(
            SimpleNamespace(
                contract=SimpleNamespace(
                    symbol="SPY",
                    primaryExchange="",
                )
            )
        )
        self.ready.set()

    monkeypatch.setattr(_OvernightContractProbe, "connect", fake_connect)
    monkeypatch.setattr(_OvernightContractProbe, "run", lambda self: None)
    monkeypatch.setattr(
        _OvernightContractProbe, "reqContractDetails", fake_req_contract_details
    )
    monkeypatch.setattr(_OvernightContractProbe, "isConnected", lambda self: False)

    result = audit_ibkr_paper_overnight_contract(
        "SPY", config=IbkrConnectionConfig(), timeout=0.0
    )
    assert result.connected is True
    assert result.base_contract_resolved is True
    assert result.overnight_contract_ready is False
    assert result.order_sent is False


def test_audit_builds_overnight_contract_from_broker_primary_exchange(monkeypatch):
    def fake_connect(self, host, port, client_id):
        self.connected_ready.set()

    def fake_req_contract_details(self, req_id, contract):
        self.details.append(
            SimpleNamespace(
                contract=SimpleNamespace(
                    symbol="SPY",
                    primaryExchange="ARCA",
                )
            )
        )
        self.ready.set()

    monkeypatch.setattr(_OvernightContractProbe, "connect", fake_connect)
    monkeypatch.setattr(_OvernightContractProbe, "run", lambda self: None)
    monkeypatch.setattr(
        _OvernightContractProbe, "reqContractDetails", fake_req_contract_details
    )
    monkeypatch.setattr(_OvernightContractProbe, "isConnected", lambda self: False)

    result = audit_ibkr_paper_overnight_contract(
        "SPY", config=IbkrConnectionConfig(), timeout=0.0
    )
    assert result.connected is True
    assert result.base_contract_resolved is True
    assert result.overnight_contract_ready is True
    assert result.primary_exchange == "ARCA"
    assert result.destination == "OVERNIGHT"
    assert result.order_sent is False
