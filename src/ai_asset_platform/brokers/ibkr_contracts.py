from __future__ import annotations

from ibapi.contract import Contract

from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.core.asset_classes import AssetClass


_IBKR_SEC_TYPES = {
    AssetClass.STOCK: "STK",
    AssetClass.ETF: "STK",
    AssetClass.FX: "CASH",
    AssetClass.FUTURE: "FUT",
    AssetClass.OPTION: "OPT",
}


def build_ibkr_contract(instrument: InstrumentSpec) -> Contract:
    """InstrumentSpecをIBKR Contractへ変換する。注文送信は行わない。

    CRYPTOは口座・地域・API経路の実証前なので意図的にFail-Closed。
    """

    sec_type = _IBKR_SEC_TYPES.get(instrument.asset_class)
    if sec_type is None:
        raise NotImplementedError(
            f"IBKR Contract未検証の商品クラスです: {instrument.asset_class.value}"
        )

    contract = Contract()
    contract.symbol = instrument.symbol.strip().upper()
    contract.secType = sec_type
    contract.exchange = instrument.exchange.strip().upper()
    contract.currency = instrument.currency.strip().upper()

    if instrument.asset_class in {AssetClass.FUTURE, AssetClass.OPTION}:
        contract.lastTradeDateOrContractMonth = instrument.expiry

    if instrument.asset_class is AssetClass.OPTION:
        contract.strike = instrument.strike
        contract.right = (instrument.right or "").upper()

    if instrument.multiplier is not None:
        contract.multiplier = instrument.multiplier

    return contract
