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
    preflight: IbkrPreflightResult | None = None,
) -> IbkrPaperTestFlowResult:
    """
    IBKR Paperテストの安全な実行フロー。

    Version 13.8では、
    1. API/TWS事前診断
    2. Paper注文安全ガード
    まで自動実行する。

    実際の注文送信はまだ行わない。
    """
    preflight = preflight or run_ibkr_paper_preflight()

    guard = validate_ibkr_paper_test_order(
        symbol,
        quantity,
        preflight=preflight,
    )

    if preflight.status != "READY_TO_CONNECT":
        return IbkrPaperTestFlowResult(
            status="WAITING",
            ready=False,
            order_sent=False,
            preflight_status=preflight.status,
            guard_status=guard.status,
            message=(
                "IBKR Paper接続準備待ちです。"
                "実注文は送信していません。"
            ),
        )

    if not guard.allowed:
        return IbkrPaperTestFlowResult(
            status="BLOCKED",
            ready=False,
            order_sent=False,
            preflight_status=preflight.status,
            guard_status=guard.status,
            message=(
                "安全ガードにより停止しました。"
                "実注文は送信していません。"
            ),
        )

    return IbkrPaperTestFlowResult(
        status="READY_FOR_PAPER_ORDER",
        ready=True,
        order_sent=False,
        preflight_status=preflight.status,
        guard_status=guard.status,
        message=(
            "IBKR Paperテスト注文を実行できる直前まで準備完了です。"
            "Version 13.8では安全のため注文送信はまだ無効です。"
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
