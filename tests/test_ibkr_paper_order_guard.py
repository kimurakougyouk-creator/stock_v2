from ai_asset_platform.brokers.ibkr_paper_order_guard import (
    validate_ibkr_paper_test_order,
)
from ai_asset_platform.brokers.ibkr_preflight import IbkrPreflightResult


def preflight(status: str) -> IbkrPreflightResult:
    ready = status == "READY_TO_CONNECT"
    return IbkrPreflightResult(
        status=status,
        api_ready=True,
        tws_port_open=ready,
        host="127.0.0.1",
        port=7497,
        message="test",
    )


def test_blocks_empty_symbol():
    result = validate_ibkr_paper_test_order(
        "",
        1,
        preflight=preflight("READY_TO_CONNECT"),
    )
    assert result.allowed is False
    assert result.status == "BLOCKED"


def test_blocks_zero_quantity():
    result = validate_ibkr_paper_test_order(
        "AAPL",
        0,
        preflight=preflight("READY_TO_CONNECT"),
    )
    assert result.allowed is False
    assert result.status == "BLOCKED"


def test_blocks_quantity_greater_than_one():
    result = validate_ibkr_paper_test_order(
        "AAPL",
        2,
        preflight=preflight("READY_TO_CONNECT"),
    )
    assert result.allowed is False
    assert result.status == "BLOCKED"


def test_waits_when_tws_not_ready():
    result = validate_ibkr_paper_test_order(
        "AAPL",
        1,
        preflight=preflight("WAITING_FOR_TWS"),
    )
    assert result.allowed is False
    assert result.status == "WAITING"


def test_allows_only_safe_ready_paper_order():
    result = validate_ibkr_paper_test_order(
        "aapl",
        1,
        preflight=preflight("READY_TO_CONNECT"),
    )
    assert result.allowed is True
    assert result.status == "READY"
    assert result.symbol == "AAPL"
    assert result.quantity == 1
