"""signal_runnerの確定売買判断をExecutionServiceへ安全に橋渡しする。"""

from dataclasses import dataclass

from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.core.asset_classes import AssetClass
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.service import ExecutionService


# 実TWS ContractDetails監査で確認済みのPaperパイロット数量だけを登録する。
# 未登録銘柄は送信層でfail-closedになる。推測で市場一律値を入れない。
_VERIFIED_PAPER_TEST_QUANTITIES = {
    "9432.T": 100,
}


@dataclass(frozen=True)
class SignalExecutionResult:
    attempted: bool
    reason: str
    broker_result: object | None = None


def _instrument_for_ticker(ticker: str) -> InstrumentSpec:
    normalized = str(ticker).strip().upper()
    verified_quantity = _VERIFIED_PAPER_TEST_QUANTITIES.get(normalized)
    if normalized.endswith(".T"):
        symbol = normalized[:-2]
        if not symbol:
            raise ValueError("Tokyo ticker symbol is empty")
        return InstrumentSpec(
            symbol=symbol,
            asset_class=AssetClass.STOCK,
            exchange="TSEJ",
            currency="JPY",
            verified_paper_test_quantity=verified_quantity,
        )
    if "." in normalized:
        raise ValueError(f"IBKR instrument mapping is not verified for ticker: {ticker}")
    return InstrumentSpec(
        symbol=normalized,
        asset_class=AssetClass.STOCK,
        exchange="SMART",
        currency="USD",
        verified_paper_test_quantity=verified_quantity,
    )


def execute_signal_via_ibkr_paper(*, service: ExecutionService, ticker: str, signal: str, shares: int, order_intent_id: str, apply_account_fill: bool = True) -> SignalExecutionResult:
    if not SETTINGS.enable_paper_trading:
        return SignalExecutionResult(False, "paper trading disabled")
    if not SETTINGS.enable_ibkr_paper:
        return SignalExecutionResult(False, "IBKR Paper disabled")
    normalized = str(signal).upper()
    if normalized not in {"BUY", "SELL"}:
        return SignalExecutionResult(False, "non-actionable signal")
    if int(shares) <= 0:
        return SignalExecutionResult(False, "invalid shares")

    instrument = _instrument_for_ticker(ticker)
    side = OrderSide.BUY if normalized == "BUY" else OrderSide.SELL
    order = OrderRequest(symbol=instrument.symbol, side=side, quantity=int(shares), order_type=OrderType.MARKET)
    result = service.execute_ibkr_paper_order(
        order,
        order_intent_id=order_intent_id,
        instrument=instrument,
        apply_account_fill=apply_account_fill,
    )
    return SignalExecutionResult(True, "submitted to IBKR Paper execution service", result)
