"""signal_runnerの確定売買判断をExecutionServiceへ安全に橋渡しする。"""

from dataclasses import dataclass

from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.core.asset_classes import AssetClass
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.service import ExecutionService


# 実TWS/Paperの証拠がある銘柄だけを明示登録する。
# 市場一律の数量推測は禁止。未登録銘柄はInstrumentSpec側で数量未確認のまま
# 送信層へ渡り、Fail-Closedで停止する。
_VERIFIED_PAPER_INSTRUMENTS = {
    "AAPL": InstrumentSpec(
        symbol="AAPL",
        asset_class=AssetClass.STOCK,
        exchange="SMART",
        currency="USD",
        verified_paper_test_quantity=1,
    ),
    "SPY": InstrumentSpec(
        symbol="SPY",
        asset_class=AssetClass.ETF,
        exchange="SMART",
        currency="USD",
        verified_paper_test_quantity=1,
    ),
    "9432.T": InstrumentSpec(
        symbol="9432",
        asset_class=AssetClass.STOCK,
        exchange="TSEJ",
        currency="JPY",
        verified_paper_test_quantity=100,
    ),
}


@dataclass(frozen=True)
class SignalExecutionResult:
    attempted: bool
    reason: str
    broker_result: object | None = None


def _instrument_for_ticker(ticker: str) -> InstrumentSpec:
    normalized = str(ticker).strip().upper()
    if not normalized:
        raise ValueError("ticker is empty")

    verified = _VERIFIED_PAPER_INSTRUMENTS.get(normalized)
    if verified is not None:
        return verified

    if normalized.endswith(".T"):
        symbol = normalized[:-2]
        if not symbol:
            raise ValueError("Tokyo ticker symbol is empty")
        return InstrumentSpec(
            symbol=symbol,
            asset_class=AssetClass.STOCK,
            exchange="TSEJ",
            currency="JPY",
            verified_paper_test_quantity=None,
        )

    if "." in normalized:
        raise ValueError(f"IBKR instrument mapping is not verified for ticker: {ticker}")

    # Generic US symbol shape is mapped only far enough for no-send/validation use.
    # Its Paper pilot quantity remains unverified until broker evidence exists.
    return InstrumentSpec(
        symbol=normalized,
        asset_class=AssetClass.STOCK,
        exchange="SMART",
        currency="USD",
        verified_paper_test_quantity=None,
    )


def verified_paper_test_quantity_for_ticker(ticker: str) -> int | None:
    """Return only broker-verified Paper pilot quantity for one explicit ticker."""
    return _instrument_for_ticker(ticker).verified_paper_test_quantity


def execute_signal_via_ibkr_paper(
    *,
    service: ExecutionService,
    ticker: str,
    signal: str,
    shares: int,
    order_intent_id: str,
    apply_account_fill: bool = True,
) -> SignalExecutionResult:
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
    order = OrderRequest(
        symbol=instrument.symbol,
        side=side,
        quantity=int(shares),
        order_type=OrderType.MARKET,
    )
    result = service.execute_ibkr_paper_order(
        order,
        order_intent_id=order_intent_id,
        instrument=instrument,
        apply_account_fill=apply_account_fill,
    )
    return SignalExecutionResult(True, "submitted to IBKR Paper execution service", result)
