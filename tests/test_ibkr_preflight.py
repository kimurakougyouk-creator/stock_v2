from ai_asset_platform.brokers import ibkr_preflight


class ReadyDiagnostic:
    status = "READY"
    message = "ready"


class NotReadyDiagnostic:
    status = "NOT_READY"
    message = "IBKR Python APIが利用できません。"


def test_preflight_waits_for_gateway_by_default(monkeypatch):
    monkeypatch.setattr(
        ibkr_preflight,
        "diagnose_ibkr_environment",
        lambda: ReadyDiagnostic(),
    )
    monkeypatch.setattr(
        ibkr_preflight,
        "_is_port_open",
        lambda host, port, timeout=1.0: False,
    )

    result = ibkr_preflight.run_ibkr_paper_preflight()

    assert result.status == "WAITING_FOR_GATEWAY"
    assert result.api_ready is True
    assert result.tws_port_open is False
    assert result.port == 4002


def test_preflight_ready_to_connect(monkeypatch):
    monkeypatch.setattr(
        ibkr_preflight,
        "diagnose_ibkr_environment",
        lambda: ReadyDiagnostic(),
    )
    monkeypatch.setattr(
        ibkr_preflight,
        "_is_port_open",
        lambda host, port, timeout=1.0: True,
    )

    result = ibkr_preflight.run_ibkr_paper_preflight()

    assert result.status == "READY_TO_CONNECT"
    assert result.api_ready is True
    assert result.tws_port_open is True
    assert result.port == 4002


def test_preflight_stops_when_api_not_ready(monkeypatch):
    monkeypatch.setattr(
        ibkr_preflight,
        "diagnose_ibkr_environment",
        lambda: NotReadyDiagnostic(),
    )
    monkeypatch.setattr(
        ibkr_preflight,
        "_is_port_open",
        lambda host, port, timeout=1.0: False,
    )

    result = ibkr_preflight.run_ibkr_paper_preflight()

    assert result.status == "NOT_READY"
    assert result.api_ready is False
    assert result.port == 4002


def test_preflight_gateway_waits_for_ib_gateway(monkeypatch):
    monkeypatch.setattr(
        ibkr_preflight,
        "diagnose_ibkr_environment",
        lambda: ReadyDiagnostic(),
    )
    monkeypatch.setattr(
        ibkr_preflight,
        "_is_port_open",
        lambda host, port, timeout=1.0: False,
    )

    result = ibkr_preflight.run_ibkr_paper_preflight(use_gateway=True)

    assert result.status == "WAITING_FOR_GATEWAY"
    assert result.api_ready is True
    assert result.tws_port_open is False
    assert result.port == 4002
    assert "IB Gateway" in result.message


def test_preflight_gateway_ready_to_connect(monkeypatch):
    monkeypatch.setattr(
        ibkr_preflight,
        "diagnose_ibkr_environment",
        lambda: ReadyDiagnostic(),
    )

    seen_ports = []

    def fake_is_port_open(host, port, timeout=1.0):
        seen_ports.append(port)
        return True

    monkeypatch.setattr(
        ibkr_preflight,
        "_is_port_open",
        fake_is_port_open,
    )

    result = ibkr_preflight.run_ibkr_paper_preflight(use_gateway=True)

    assert result.status == "READY_TO_CONNECT"
    assert result.api_ready is True
    assert result.tws_port_open is True
    assert result.host == "127.0.0.1"
    assert result.port == 4002
    assert seen_ports == [4002]


def test_preflight_gateway_api_not_ready_reports_gateway_port(monkeypatch):
    monkeypatch.setattr(
        ibkr_preflight,
        "diagnose_ibkr_environment",
        lambda: NotReadyDiagnostic(),
    )
    monkeypatch.setattr(
        ibkr_preflight,
        "_is_port_open",
        lambda host, port, timeout=1.0: False,
    )

    result = ibkr_preflight.run_ibkr_paper_preflight(use_gateway=True)

    assert result.status == "NOT_READY"
    assert result.api_ready is False
    assert result.port == 4002


def test_preflight_tws_can_be_selected_explicitly(monkeypatch):
    monkeypatch.setattr(
        ibkr_preflight,
        "diagnose_ibkr_environment",
        lambda: ReadyDiagnostic(),
    )
    monkeypatch.setattr(
        ibkr_preflight,
        "_is_port_open",
        lambda host, port, timeout=1.0: False,
    )

    result = ibkr_preflight.run_ibkr_paper_preflight(use_gateway=False)

    assert result.status == "WAITING_FOR_TWS"
    assert result.api_ready is True
    assert result.tws_port_open is False
    assert result.port == 7497
