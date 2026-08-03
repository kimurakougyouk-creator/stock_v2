from ai_asset_platform.brokers import ibkr_readiness
from ai_asset_platform.brokers.ibkr_preflight import IbkrPreflightResult


class ReadyDiagnostic:
    status = "READY"
    message = "ready"


class NotReadyDiagnostic:
    status = "NOT_READY"
    message = "api not ready"


def make_preflight(status: str) -> IbkrPreflightResult:
    ready = status == "READY_TO_CONNECT"
    return IbkrPreflightResult(
        status=status,
        api_ready=True,
        tws_port_open=ready,
        host="127.0.0.1",
        port=7497,
        message="test",
    )


def test_waits_for_tws_when_python_is_ready(monkeypatch):
    monkeypatch.setattr(
        ibkr_readiness,
        "diagnose_ibkr_environment",
        lambda: ReadyDiagnostic(),
    )

    result = ibkr_readiness.evaluate_ibkr_readiness(
        preflight=make_preflight("WAITING_FOR_TWS"),
    )

    assert result.status == "WAITING_FOR_TWS"
    assert result.ready_for_connection is False
    assert result.ready_for_paper_order is False
    assert result.order_transmission_enabled is False


def test_ready_for_connection_but_transmission_stays_disabled(monkeypatch):
    monkeypatch.setattr(
        ibkr_readiness,
        "diagnose_ibkr_environment",
        lambda: ReadyDiagnostic(),
    )

    result = ibkr_readiness.evaluate_ibkr_readiness(
        preflight=make_preflight("READY_TO_CONNECT"),
    )

    assert result.status == "READY_FOR_PAPER_CONNECTION_TEST"
    assert result.ready_for_connection is True
    assert result.ready_for_paper_order is True
    assert result.order_transmission_enabled is False


def test_stops_when_python_api_is_not_ready(monkeypatch):
    monkeypatch.setattr(
        ibkr_readiness,
        "diagnose_ibkr_environment",
        lambda: NotReadyDiagnostic(),
    )

    result = ibkr_readiness.evaluate_ibkr_readiness(
        preflight=make_preflight("READY_TO_CONNECT"),
    )

    assert result.status == "PYTHON_API_NOT_READY"
    assert result.ready_for_connection is False
    assert result.ready_for_paper_order is False
    assert result.order_transmission_enabled is False
