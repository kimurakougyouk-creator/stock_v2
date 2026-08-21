from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_contracts import build_ibkr_contract_spec, to_ibapi_contract
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.core.asset_classes import AssetClass


@dataclass(frozen=True)
class IbkrOrderSizeRule:
    symbol: str
    min_size: float | None
    size_increment: float | None
    suggested_size_increment: float | None


class _ContractDetailsProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.ready = Event()
        self.done = Event()
        self.details = []
        self.errors: list[dict] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def contractDetails(self, reqId, contractDetails) -> None:  # noqa: N802
        self.details.append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.done.set()

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):
        self.errors.append({
            "req_id": reqId,
            "code": int(errorCode),
            "message": str(errorString),
        })
        if int(errorCode) in {502, 503, 504, 1100}:
            self.ready.set()
            self.done.set()


def _optional_positive_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def extract_order_size_rule(contract_details) -> IbkrOrderSizeRule:
    contract = contract_details.contract
    return IbkrOrderSizeRule(
        symbol=str(getattr(contract, "symbol", "")),
        min_size=_optional_positive_float(getattr(contract_details, "minSize", None)),
        size_increment=_optional_positive_float(getattr(contract_details, "sizeIncrement", None)),
        suggested_size_increment=_optional_positive_float(
            getattr(contract_details, "suggestedSizeIncrement", None)
        ),
    )


def audit_ibkr_order_size(
    instrument: InstrumentSpec,
    *,
    timeout: float = 8.0,
) -> tuple[list[IbkrOrderSizeRule], list[dict]]:
    """Paper TWSへ接続しContractDetailsだけを読む。注文は絶対に送信しない。"""
    config = create_ibkr_paper_config()
    config.validate()
    if not config.paper_trading or config.allow_live_trading:
        raise RuntimeError("Paper専用設定ではないため注文単位監査を中止しました。")

    probe = _ContractDetailsProbe()
    try:
        probe.connect(config.host, config.port, config.client_id + 17)
        thread = Thread(target=probe.run, daemon=True)
        thread.start()
        if not probe.ready.wait(timeout):
            raise RuntimeError("IBKR Paper APIへの接続を確認できませんでした。")

        contract = to_ibapi_contract(build_ibkr_contract_spec(instrument))
        probe.reqContractDetails(9432001, contract)
        if not probe.done.wait(timeout):
            raise RuntimeError("IBKR ContractDetailsがタイムアウトしました。")

        return [extract_order_size_rule(item) for item in probe.details], list(probe.errors)
    finally:
        if probe.isConnected():
            probe.disconnect()


def main() -> None:
    instrument = InstrumentSpec(
        symbol="9432",
        asset_class=AssetClass.STOCK,
        exchange="TSEJ",
        currency="JPY",
    )
    rules, errors = audit_ibkr_order_size(instrument)
    print("===== IBKR ORDER SIZE AUDIT (NO ORDER) =====")
    print("SYMBOL     : 9432")
    print("EXCHANGE   : TSEJ")
    print("CURRENCY   : JPY")
    print("ORDER SENT : False")
    if not rules:
        print("RULES      : NOT RESOLVED")
    for index, rule in enumerate(rules, start=1):
        print(f"RULE {index} MIN SIZE             : {rule.min_size}")
        print(f"RULE {index} SIZE INCREMENT       : {rule.size_increment}")
        print(f"RULE {index} SUGGESTED INCREMENT  : {rule.suggested_size_increment}")
    relevant_errors = [e for e in errors if e["code"] not in {2104, 2106, 2107, 2158}]
    print(f"RELEVANT ERRORS: {relevant_errors}")


if __name__ == "__main__":
    main()
