from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_preflight import IbkrPreflightResult, run_ibkr_paper_preflight


@dataclass(frozen=True)
class IbkrPaperOrderGuardResult:
    status: str
    allowed: bool
    symbol: str
    quantity: int
    message: str


def validate_ibkr_paper_test_order(symbol: str, quantity: int, *, verified_test_quantity: int = 1, preflight: IbkrPreflightResult | None = None, use_gateway: bool = False) -> IbkrPaperOrderGuardResult:
    """Fail-closed Paper guard. Default verified quantity remains 1."""
    symbol = symbol.strip().upper()
    if not symbol:
        return IbkrPaperOrderGuardResult("BLOCKED", False, symbol, quantity, "銘柄コードが空のため停止しました。")
    if quantity <= 0:
        return IbkrPaperOrderGuardResult("BLOCKED", False, symbol, quantity, "注文数量は1以上にしてください。")
    if verified_test_quantity <= 0:
        return IbkrPaperOrderGuardResult("BLOCKED", False, symbol, quantity, "検証済みPaperテスト数量が不正なため停止しました。")
    if quantity != verified_test_quantity:
        return IbkrPaperOrderGuardResult("BLOCKED", False, symbol, quantity, f"IBKR Paperテスト注文は検証済み数量{verified_test_quantity}だけ許可します。")

    config = create_ibkr_paper_config(use_gateway=use_gateway)
    if not config.paper_trading:
        return IbkrPaperOrderGuardResult("BLOCKED", False, symbol, quantity, "Paper Trading設定ではないため停止しました。")
    if config.allow_live_trading:
        return IbkrPaperOrderGuardResult("BLOCKED", False, symbol, quantity, "Live Trading許可中のため停止しました。")

    preflight = preflight or run_ibkr_paper_preflight(use_gateway=use_gateway)
    if preflight.status != "READY_TO_CONNECT":
        return IbkrPaperOrderGuardResult("WAITING", False, symbol, quantity, "IBKR Paper接続準備が完了していないため注文を許可しません。" f" preflight={preflight.status}")
    return IbkrPaperOrderGuardResult("READY", True, symbol, quantity, "IBKR Paperテスト注文の事前条件を満たしました。この判定だけでは注文は送信されません。")


def main() -> None:
    result = validate_ibkr_paper_test_order("AAPL", 1)
    print("===== IBKR PAPER ORDER GUARD =====")
    print(f"STATUS  : {result.status}")
    print(f"ALLOWED : {result.allowed}")
    print(f"SYMBOL  : {result.symbol}")
    print(f"QUANTITY: {result.quantity}")
    print(f"MESSAGE : {result.message}")


if __name__ == "__main__":
    main()
