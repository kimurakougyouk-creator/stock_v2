from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_preflight import (
    IbkrPreflightResult,
    run_ibkr_paper_preflight,
)


@dataclass(frozen=True)
class IbkrPaperOrderGuardResult:
    status: str
    allowed: bool
    symbol: str
    quantity: int
    message: str


def validate_ibkr_paper_test_order(
    symbol: str,
    quantity: int,
    *,
    preflight: IbkrPreflightResult | None = None,
    use_gateway: bool = False,
) -> IbkrPaperOrderGuardResult:
    """
    IBKR Paperテスト注文を送る「前」だけを検証する安全ガード。

    この関数自身は注文を一切送信しない。

    use_gateway=False (デフォルト) はTWS Paper Trading (127.0.0.1:7497)、
    use_gateway=True はIB Gateway Paper Trading (127.0.0.1:4002) を対象にする。
    preflightを明示的に渡した場合はuse_gatewayより優先される。
    既存呼び出し側の動作(TWS/7497)はデフォルト値により変わらない。
    """
    symbol = symbol.strip().upper()

    if not symbol:
        return IbkrPaperOrderGuardResult(
            status="BLOCKED",
            allowed=False,
            symbol=symbol,
            quantity=quantity,
            message="銘柄コードが空のため停止しました。",
        )

    if quantity <= 0:
        return IbkrPaperOrderGuardResult(
            status="BLOCKED",
            allowed=False,
            symbol=symbol,
            quantity=quantity,
            message="注文数量は1以上にしてください。",
        )

    # 初回Paperテストは意図しない大量注文を防ぐため1単位だけに固定。
    if quantity != 1:
        return IbkrPaperOrderGuardResult(
            status="BLOCKED",
            allowed=False,
            symbol=symbol,
            quantity=quantity,
            message="初回IBKR Paperテスト注文は数量1だけ許可します。",
        )

    config = create_ibkr_paper_config(use_gateway=use_gateway)

    if not config.paper_trading:
        return IbkrPaperOrderGuardResult(
            status="BLOCKED",
            allowed=False,
            symbol=symbol,
            quantity=quantity,
            message="Paper Trading設定ではないため停止しました。",
        )

    if config.allow_live_trading:
        return IbkrPaperOrderGuardResult(
            status="BLOCKED",
            allowed=False,
            symbol=symbol,
            quantity=quantity,
            message="Live Trading許可中のため停止しました。",
        )

    preflight = preflight or run_ibkr_paper_preflight(use_gateway=use_gateway)

    if preflight.status != "READY_TO_CONNECT":
        return IbkrPaperOrderGuardResult(
            status="WAITING",
            allowed=False,
            symbol=symbol,
            quantity=quantity,
            message=(
                "IBKR Paper接続準備が完了していないため注文を許可しません。"
                f" preflight={preflight.status}"
            ),
        )

    return IbkrPaperOrderGuardResult(
        status="READY",
        allowed=True,
        symbol=symbol,
        quantity=quantity,
        message=(
            "IBKR Paperテスト注文の事前条件を満たしました。"
            "この判定だけでは注文は送信されません。"
        ),
    )


def main() -> None:
    # 診断専用。実注文は絶対に送らない。
    result = validate_ibkr_paper_test_order("AAPL", 1)

    print("===== IBKR PAPER ORDER GUARD =====")
    print(f"STATUS  : {result.status}")
    print(f"ALLOWED : {result.allowed}")
    print(f"SYMBOL  : {result.symbol}")
    print(f"QUANTITY: {result.quantity}")
    print(f"MESSAGE : {result.message}")


if __name__ == "__main__":
    main()
