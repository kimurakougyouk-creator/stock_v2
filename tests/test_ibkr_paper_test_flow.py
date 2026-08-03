from ai_asset_platform.brokers.ibkr_paper_test_flow import (
    run_ibkr_paper_test_flow,
)
from ai_asset_platform.brokers.ibkr_preflight import IbkrPreflightResult


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


def test_flow_waits_when_tws_not_ready():
    result = run_ibkr_paper_test_flow(
        preflight=make_preflight("WAITING_FOR_TWS"),
    )

    assert result.status == "WAITING"
    assert result.ready is False
    assert result.order_sent is False
    assert result.preflight_status == "WAITING_FOR_TWS"


def test_flow_ready_but_never_sends_order():
    result = run_ibkr_paper_test_flow(
        preflight=make_preflight("READY_TO_CONNECT"),
    )

    assert result.status == "READY_FOR_PAPER_ORDER"
    assert result.ready is True
    assert result.order_sent is False
    assert result.guard_status == "READY"


def test_flow_blocks_unsafe_quantity():
    result = run_ibkr_paper_test_flow(
        quantity=2,
        preflight=make_preflight("READY_TO_CONNECT"),
    )

    assert result.status == "BLOCKED"
    assert result.ready is False
    assert result.order_sent is False
    assert result.guard_status == "BLOCKED"


def test_flow_blocks_empty_symbol():
    result = run_ibkr_paper_test_flow(
        symbol="",
        preflight=make_preflight("READY_TO_CONNECT"),
    )

    assert result.status == "BLOCKED"
    assert result.ready is False
    assert result.order_sent is False


def test_flow_normalizes_safe_symbol():
    result = run_ibkr_paper_test_flow(
        symbol="aapl",
        quantity=1,
        preflight=make_preflight("READY_TO_CONNECT"),
    )

    assert result.status == "READY_FOR_PAPER_ORDER"
    assert result.ready is True
    assert result.order_sent is False
