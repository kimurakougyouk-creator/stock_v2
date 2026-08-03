from ai_asset_platform.brokers import ibkr_preflight


class ReadyDiagnostic:
    status = "READY"
    message = "ready"


class NotReadyDiagnostic:
    status = "NOT_READY"
    message = "IBKR Python APIが利用できません。"


def test_preflight_waits_for_tws(monkeypatch):
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

    assert result.status == "WAITING_FOR_TWS"
    assert result.api_ready is True
    assert result.tws_port_open is False
    assert result.port == 7497


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
    assert result.port == 7497


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
