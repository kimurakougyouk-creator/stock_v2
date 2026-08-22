from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr_paper_order_guard import (
    validate_ibkr_paper_test_order,
)
from ai_asset_platform.brokers.ibkr_preflight import (
    IbkrPreflightResult,
    run_ibkr_paper_preflight,
)


@dataclass(frozen=True)
class IbkrPaperTestFlowResult:
    status: str
    ready: bool
    order_sent: bool
    preflight_status: str
    guard_status: str
    message: str


def run_ibkr_paper_test_flow(
    symbol: str = "AAPL",
    quantity: int = 1,
    *,
    verified_test_quantity: int | None = 1,
    preflight: IbkrPreflightResult | None = None,
) -> IbkrPaperTestFlowResult:
    """Run the legacy verified US-stock Paper readiness flow without sending an order.

    New products and markets must pass their product-specific verified quantity
    explicitly. The default of one is retained only for this historical US-stock
    test-flow entry point, whose one-share path was already broker-verified.
    """
    preflight = preflight or run_ibkr_paper_preflight()

    guard = validate_ibkr_paper_test_order(
        symbol,
        quantity,
        verified_test_quantity=verified_test_quantity,
        preflight=preflight,
    )

    if preflight.status != "READY_TO_CONNECT":
        return IbkrPaperTestFlowResult(
            status="WAITING",
            ready=False,
            order_sent=False,
            preflight_status=preflight.status,
            guard_status=guard.status,
            message="IBKR Paper接続準備待ちです。実注文は送信していません。",
        )

    if not guard.allowed:
        return IbkrPaperTestFlowResult(
            status="BLOCKED",
            ready=False,
            order_sent=False,
            preflight_status=preflight.status,
            guard_status=guard.status,
            message="安全ガードにより停止しました。実注文は送信していません。",
        )

    return IbkrPaperTestFlowResult(
        status="READY_FOR_PAPER_ORDER",
        ready=True,
        order_sent=False,
        preflight_status=preflight.status,
        guard_status=guard.status,
        message=(
            "IBKR Paperテスト注文を実行できる直前まで準備完了です。"
            "この確認フローでは注文を送信していません。"
        ),
    )


def main() -> None:
    result = run_ibkr_paper_test_flow()
    print("===== IBKR PAPER TEST FLOW =====")
    print(f"STATUS          : {result.status}")
    print(f"READY           : {result.ready}")
    print(f"ORDER SENT      : {result.order_sent}")
    print(f"PREFLIGHT STATUS: {result.preflight_status}")
    print(f"GUARD STATUS    : {result.guard_status}")
    print(f"MESSAGE         : {result.message}")


if __name__ == "__main__":
    main()
