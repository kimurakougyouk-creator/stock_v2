from types import SimpleNamespace

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
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


def test_contract_details_probe_marks_connection_ready_on_next_valid_id():
    probe = _ContractDetailsProbe()
    assert not probe.connected_ready.is_set()
    probe.nextValidId(123)
    assert probe.connected_ready.is_set()


def test_contract_details_probe_marks_duplicate_client_id_fatal():
    probe = _ContractDetailsProbe()
    probe.error(1, 0, 326, "Unable to connect as the client id is already in use")
    assert probe.fatal_error.startswith("326:")
    assert probe.connected_ready.is_set()
    assert probe.ready.is_set()


def test_contract_details_probe_marks_fatal_contract_error():
    probe = _ContractDetailsProbe()
    probe.error(1, 0, 200, "No security definition")
    assert probe.fatal_error == "200: No security definition"
    assert probe.ready.is_set()


def test_contract_details_probe_preserves_nonfatal_errors_for_diagnostics():
    probe = _ContractDetailsProbe()
    probe.error(1, 0, 2104, "Market data farm connection is OK")
    assert "2104:" in probe.diagnostic_suffix()
    assert probe.fatal_error is None


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


def test_etf_audit_uses_isolated_client_id_for_contract_session(monkeypatch):
    observed: dict[str, int] = {}
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_etf_audit.probe_ibkr_paper_connection",
        lambda config, timeout: IbkrConnectionResult(True, 10, "connected"),
    )

    def fake_connect(self, host, port, client_id):
        observed["client_id"] = client_id
        self.connected_ready.set()

    def fake_req_contract_details(self, req_id, contract):
        self.ready.set()

    monkeypatch.setattr(_ContractDetailsProbe, "connect", fake_connect)
    monkeypatch.setattr(_ContractDetailsProbe, "run", lambda self: None)
    monkeypatch.setattr(_ContractDetailsProbe, "reqContractDetails", fake_req_contract_details)
    monkeypatch.setattr(_ContractDetailsProbe, "isConnected", lambda self: False)

    cfg = IbkrConnectionConfig(client_id=41)
    result = audit_ibkr_paper_etf("SPY", config=cfg, timeout=0.0)
    assert observed["client_id"] == 142
    assert result.connected is True
    assert result.contract_resolved is False
    assert result.order_sent is False
