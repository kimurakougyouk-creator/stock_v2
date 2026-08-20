from ai_asset_platform.brokers.ibkr_connection import IbkrConnectionResult
from ai_asset_platform.brokers.ibkr_paper_order_guard import IbkrPaperOrderGuardResult
from ai_asset_platform.brokers.ibkr_paper_smoke_test import run_ibkr_paper_smoke_test
from ai_asset_platform.brokers.ibkr_preflight import IbkrPreflightResult


def _ready_preflight():
    return IbkrPreflightResult(
        status="READY_TO_CONNECT",
        api_ready=True,
        tws_port_open=True,
        host="127.0.0.1",
        port=4002,
        message="ready",
    )


def test_smoke_test_reaches_ready_without_sending_order(monkeypatch):
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_smoke_test.run_ibkr_paper_preflight",
        lambda **kwargs: _ready_preflight(),
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_smoke_test.validate_ibkr_paper_test_order",
        lambda *args, **kwargs: IbkrPaperOrderGuardResult(
            status="READY", allowed=True, symbol="AAPL", quantity=1, message="ready"
        ),
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_smoke_test.probe_ibkr_paper_connection",
        lambda *args, **kwargs: IbkrConnectionResult(
            connected=True, next_order_id=123, message="connected"
        ),
    )

    result = run_ibkr_paper_smoke_test()

    assert result.status == "READY_FOR_MINIMAL_PAPER_ORDER"
    assert result.connected is True
    assert result.next_order_id == 123
    assert result.order_sent is False


def test_smoke_test_stops_when_preflight_is_not_ready(monkeypatch):
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_smoke_test.run_ibkr_paper_preflight",
        lambda **kwargs: IbkrPreflightResult(
            status="WAITING_FOR_TWS",
            api_ready=True,
            tws_port_open=False,
            host="127.0.0.1",
            port=4002,
            message="waiting",
        ),
    )

    result = run_ibkr_paper_smoke_test()

    assert result.status == "PREFLIGHT_BLOCKED"
    assert result.connected is False
    assert result.order_sent is False
