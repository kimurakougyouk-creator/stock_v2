from ai_asset_platform.brokers import ibkr_paper_order_guard
from ai_asset_platform.brokers.ibkr_paper_order_guard import (
    validate_ibkr_paper_test_order,
)
from ai_asset_platform.brokers.ibkr_preflight import IbkrPreflightResult


def preflight(status: str, port: int = 7497) -> IbkrPreflightResult:
    ready = status == "READY_TO_CONNECT"
    return IbkrPreflightResult(
        status=status,
        api_ready=True,
        tws_port_open=ready,
        host="127.0.0.1",
        port=port,
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


def test_allows_safe_ready_paper_order_via_gateway():
    result = validate_ibkr_paper_test_order(
        "aapl",
        1,
        preflight=preflight("READY_TO_CONNECT", port=4002),
        use_gateway=True,
    )
    assert result.allowed is True
    assert result.status == "READY"
    assert result.symbol == "AAPL"
    assert result.quantity == 1


def test_gateway_flag_without_preflight_uses_gateway_port(monkeypatch):
    """preflightを省略した場合、use_gateway=TrueはGateway(4002)を診断すること。"""
    seen_use_gateway = []

    def fake_preflight(*, use_gateway=False):
        seen_use_gateway.append(use_gateway)
        return preflight("READY_TO_CONNECT", port=4002)

    monkeypatch.setattr(
        ibkr_paper_order_guard,
        "run_ibkr_paper_preflight",
        fake_preflight,
    )

    result = validate_ibkr_paper_test_order("AAPL", 1, use_gateway=True)

    assert seen_use_gateway == [True]
    assert result.allowed is True
    assert result.status == "READY"


def test_default_use_gateway_is_false_and_uses_tws_port(monkeypatch):
    """use_gatewayを省略した既存呼び出しはTWS(7497)のままであること。"""
    seen_use_gateway = []

    def fake_preflight(*, use_gateway=False):
        seen_use_gateway.append(use_gateway)
        return preflight("READY_TO_CONNECT", port=7497)

    monkeypatch.setattr(
        ibkr_paper_order_guard,
        "run_ibkr_paper_preflight",
        fake_preflight,
    )

    result = validate_ibkr_paper_test_order("AAPL", 1)

    assert seen_use_gateway == [False]
    assert result.allowed is True
