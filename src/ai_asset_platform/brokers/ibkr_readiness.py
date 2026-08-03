from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_diagnostics import diagnose_ibkr_environment
from ai_asset_platform.brokers.ibkr_paper_order_sender import (
    prepare_ibkr_paper_order,
)
from ai_asset_platform.brokers.ibkr_preflight import (
    IbkrPreflightResult,
    run_ibkr_paper_preflight,
)
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide


@dataclass(frozen=True)
class IbkrReadinessResult:
    status: str
    ready_for_connection: bool
    ready_for_paper_order: bool
    order_transmission_enabled: bool
    next_action: str
    message: str


def evaluate_ibkr_readiness(
    *,
    preflight: IbkrPreflightResult | None = None,
) -> IbkrReadinessResult:
    """
    IBKR Paper実機テスト前の総合判定。

    注文送信は一切行わない。
    """
    config = create_ibkr_paper_config()
    config.validate()

    diagnostic = diagnose_ibkr_environment()

    if diagnostic.status != "READY":
        return IbkrReadinessResult(
            status="PYTHON_API_NOT_READY",
            ready_for_connection=False,
            ready_for_paper_order=False,
            order_transmission_enabled=False,
            next_action="IBKR Python API環境を修復する",
            message=diagnostic.message,
        )

    preflight = preflight or run_ibkr_paper_preflight()

    if preflight.status != "READY_TO_CONNECT":
        return IbkrReadinessResult(
            status="WAITING_FOR_TWS",
            ready_for_connection=False,
            ready_for_paper_order=False,
            order_transmission_enabled=False,
            next_action="IBKR承認後、TWSへPaper Tradingでログインする",
            message=(
                "Python側の準備は完了しています。"
                "現在はTWS Paper APIの準備待ちです。"
            ),
        )

    prepared = prepare_ibkr_paper_order(
        OrderRequest(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=1,
        ),
        config,
    )

    if prepared.order.transmit:
        return IbkrReadinessResult(
            status="SAFETY_ERROR",
            ready_for_connection=True,
            ready_for_paper_order=False,
            order_transmission_enabled=True,
            next_action="注文送信を停止して安全設定を確認する",
            message="承認前の注文送信ロックが解除されています。",
        )

    return IbkrReadinessResult(
        status="READY_FOR_PAPER_CONNECTION_TEST",
        ready_for_connection=True,
        ready_for_paper_order=True,
        order_transmission_enabled=False,
        next_action="PythonからTWS Paper APIへの実接続テストを行う",
        message=(
            "Paper実機テスト直前まで準備完了です。"
            "注文送信はまだ無効です。"
        ),
    )


def main() -> None:
    result = evaluate_ibkr_readiness()

    print("===== IBKR READINESS =====")
    print(f"STATUS                    : {result.status}")
    print(f"READY FOR CONNECTION      : {result.ready_for_connection}")
    print(f"READY FOR PAPER ORDER     : {result.ready_for_paper_order}")
    print(
        "ORDER TRANSMISSION ENABLED:",
        result.order_transmission_enabled,
    )
    print(f"NEXT ACTION               : {result.next_action}")
    print(f"MESSAGE                   : {result.message}")


if __name__ == "__main__":
    main()
