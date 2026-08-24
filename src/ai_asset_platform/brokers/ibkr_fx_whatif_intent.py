"""Pure fail-closed intent validation for a future IBKR FX Paper what-if.

This module intentionally does not create an IB API Order and never connects to
a broker. It exists to make the ambiguous parts of FX order semantics explicit
before any no-transmit broker preview is attempted.

IBKR exposes both regular order quantity and cash-quantity fields for forex.
This module therefore never chooses a quantity field implicitly. The caller
must explicitly select TOTAL_QUANTITY or CASH_QUANTITY. Broker ContractDetails
size constraints are applied only to TOTAL_QUANTITY here; their applicability
to CASH_QUANTITY is not assumed.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

from ai_asset_platform.brokers.ibkr_fx_contracts import (
    VerifiedFxContractInput,
    build_verified_fx_contract,
)
from ai_asset_platform.brokers.orders import OrderSide


class FxQuantityMode(str, Enum):
    TOTAL_QUANTITY = "TOTAL_QUANTITY"
    CASH_QUANTITY = "CASH_QUANTITY"


@dataclass(frozen=True)
class FxWhatIfIntentInput:
    base_currency: str
    quote_currency: str
    exchange: str
    con_id: int
    side: OrderSide
    quantity_mode: FxQuantityMode
    quantity: float
    limit_price: float
    local_symbol: str | None = None
    min_size: float | None = None
    size_increment: float | None = None


@dataclass(frozen=True)
class VerifiedFxWhatIfIntent:
    contract_input: VerifiedFxContractInput
    side: OrderSide
    quantity_mode: FxQuantityMode
    quantity: Decimal
    limit_price: Decimal
    min_size: Decimal | None
    size_increment: Decimal | None

    @property
    def real_order_allowed(self) -> bool:
        return False


def _positive_decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _optional_positive_decimal(value: object | None, *, field: str) -> Decimal | None:
    if value is None:
        return None
    return _positive_decimal(value, field=field)


def _is_increment_aligned(quantity: Decimal, increment: Decimal) -> bool:
    return quantity % increment == 0


def verify_fx_whatif_intent(spec: FxWhatIfIntentInput) -> VerifiedFxWhatIfIntent:
    """Validate explicit FX what-if semantics without creating/sending an Order."""
    if not isinstance(spec.side, OrderSide):
        raise ValueError("FX side must be an explicit OrderSide")
    if not isinstance(spec.quantity_mode, FxQuantityMode):
        raise ValueError("FX quantity_mode must be explicit")
    if int(spec.con_id) <= 0:
        raise ValueError("FX con_id must be positive")

    quantity = _positive_decimal(spec.quantity, field="FX quantity")
    limit_price = _positive_decimal(spec.limit_price, field="FX limit_price")

    if spec.quantity_mode is FxQuantityMode.CASH_QUANTITY:
        if spec.min_size is not None or spec.size_increment is not None:
            raise ValueError(
                "FX CASH_QUANTITY broker min_size/size_increment semantics are unverified"
            )
        min_size = None
        size_increment = None
    else:
        min_size = _optional_positive_decimal(spec.min_size, field="FX min_size")
        size_increment = _optional_positive_decimal(
            spec.size_increment, field="FX size_increment"
        )
        if min_size is not None and quantity < min_size:
            raise ValueError("FX quantity is below broker min_size")
        if size_increment is not None and not _is_increment_aligned(quantity, size_increment):
            raise ValueError("FX quantity is not aligned to broker size_increment")

    contract_input = VerifiedFxContractInput(
        base_currency=spec.base_currency,
        quote_currency=spec.quote_currency,
        exchange=spec.exchange,
        local_symbol=spec.local_symbol,
        con_id=int(spec.con_id),
    )
    # Reuse the existing fail-closed Contract validation now, but discard the
    # object here. A later broker what-if adapter may build it again only after
    # this intent has passed all explicit gates.
    build_verified_fx_contract(contract_input)

    return VerifiedFxWhatIfIntent(
        contract_input=contract_input,
        side=spec.side,
        quantity_mode=spec.quantity_mode,
        quantity=quantity,
        limit_price=limit_price,
        min_size=min_size,
        size_increment=size_increment,
    )
