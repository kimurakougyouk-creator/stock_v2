"""Evidence ledger for issue #56 multi-asset verification.

This module is deliberately descriptive, not an order-permission switch.  It
separates four different ideas that must never be conflated:

* a repository-only Contract foundation,
* broker read-only runtime evidence,
* one controlled instrument's real Paper E2E evidence, and
* a market-level entry in VERIFIED_CAPABILITIES.

Adding evidence here does not make an order transmittable.  Actual order paths
retain their own product-specific fail-closed gates, and Live remains disabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ai_asset_platform.core.asset_classes import AssetClass, is_verified_paper_capability


class VerificationLevel(str, Enum):
    CONTRACT_FOUNDATION = "CONTRACT_FOUNDATION"
    READ_ONLY_RUNTIME = "READ_ONLY_RUNTIME"
    CONTROLLED_INSTRUMENT_PAPER = "CONTROLLED_INSTRUMENT_PAPER"
    VERIFIED_MARKET_PAPER = "VERIFIED_MARKET_PAPER"


@dataclass(frozen=True)
class AssetVerificationEvidence:
    key: str
    asset_class: AssetClass
    level: VerificationLevel
    contract_foundation: bool
    runtime_contract_evidence: bool
    product_specific_order_path: bool
    trusted_accounting_path: bool
    real_paper_e2e: bool
    capability_promoted: bool
    controlled_instrument: str | None = None
    remaining_gates: tuple[str, ...] = ()
    live_supported: bool = False

    @property
    def paper_market_verified(self) -> bool:
        """True only for a market-level capability already promoted elsewhere."""
        return self.level is VerificationLevel.VERIFIED_MARKET_PAPER and self.capability_promoted


# Facts below are intentionally conservative and correspond to verified evidence
# already recorded in PROJECT_STATE / issue #56 as of 2026-08-24.
MULTI_ASSET_VERIFICATION: tuple[AssetVerificationEvidence, ...] = (
    AssetVerificationEvidence(
        key="US_ETF",
        asset_class=AssetClass.ETF,
        level=VerificationLevel.VERIFIED_MARKET_PAPER,
        contract_foundation=True,
        runtime_contract_evidence=True,
        product_specific_order_path=True,
        trusted_accounting_path=True,
        real_paper_e2e=True,
        capability_promoted=True,
        controlled_instrument="SPY",
        remaining_gates=(),
    ),
    AssetVerificationEvidence(
        key="GLOBAL_STOCK_CONTROLLED_9432_TSEJ_JPY",
        asset_class=AssetClass.STOCK,
        level=VerificationLevel.CONTROLLED_INSTRUMENT_PAPER,
        contract_foundation=True,
        runtime_contract_evidence=True,
        product_specific_order_path=True,
        trusted_accounting_path=True,
        real_paper_e2e=True,
        capability_promoted=False,
        controlled_instrument="9432/TSEJ/JPY",
        remaining_gates=(
            "broader global-stock symbols/venues are not generalized by one controlled E2E",
            "no market-level global-stock capability entry is justified yet",
        ),
    ),
    AssetVerificationEvidence(
        key="FX_USD_JPY_IDEALPRO",
        asset_class=AssetClass.FX,
        level=VerificationLevel.READ_ONLY_RUNTIME,
        contract_foundation=True,
        runtime_contract_evidence=True,
        product_specific_order_path=False,
        trusted_accounting_path=False,
        real_paper_e2e=False,
        capability_promoted=False,
        controlled_instrument="USD/JPY@IDEALPRO",
        remaining_gates=(
            "explicit product-specific Paper no-transmit/what-if order gate",
            "verified FX quantity/direction/order-type semantics",
            "FX fill-to-accounting/trade-history/equity/drawdown/restart path",
            "real Paper E2E before capability promotion",
        ),
    ),
    AssetVerificationEvidence(
        key="FUTURES",
        asset_class=AssetClass.FUTURE,
        level=VerificationLevel.CONTRACT_FOUNDATION,
        contract_foundation=True,
        runtime_contract_evidence=False,
        product_specific_order_path=False,
        trusted_accounting_path=False,
        real_paper_e2e=False,
        capability_promoted=False,
        remaining_gates=(
            "explicit intended future + exchange + expiry broker runtime evidence",
            "verified multiplier/min-size/tick and lifecycle/roll/settlement rules",
            "derivative-specific sizing/accounting/restart path",
            "no-transmit order gate and real Paper E2E",
        ),
    ),
    AssetVerificationEvidence(
        key="OPTIONS",
        asset_class=AssetClass.OPTION,
        level=VerificationLevel.CONTRACT_FOUNDATION,
        contract_foundation=True,
        runtime_contract_evidence=False,
        product_specific_order_path=False,
        trusted_accounting_path=False,
        real_paper_e2e=False,
        capability_promoted=False,
        remaining_gates=(
            "explicit broker runtime resolution for expiry/strike/right/multiplier",
            "exercise/assignment/expiry/settlement risk handling",
            "derivative-specific sizing/accounting/restart path",
            "no-transmit order gate and real Paper E2E",
        ),
    ),
    AssetVerificationEvidence(
        key="CRYPTO",
        asset_class=AssetClass.CRYPTO,
        level=VerificationLevel.CONTRACT_FOUNDATION,
        contract_foundation=True,
        runtime_contract_evidence=False,
        product_specific_order_path=False,
        trusted_accounting_path=False,
        real_paper_e2e=False,
        capability_promoted=False,
        remaining_gates=(
            "account/residence/venue/Paper availability must be verified, not inferred",
            "broker runtime contract/market-data/min-size evidence",
            "crypto-specific sizing/accounting/order path",
            "no-transmit order gate and real Paper E2E",
        ),
    ),
)


def evidence_for(key: str) -> AssetVerificationEvidence:
    normalized = str(key).strip().upper()
    for item in MULTI_ASSET_VERIFICATION:
        if item.key == normalized:
            return item
    raise KeyError(f"unknown multi-asset verification key: {key}")


def validate_verification_matrix() -> tuple[str, ...]:
    """Return invariant violations without granting any trading permission."""
    violations: list[str] = []
    for item in MULTI_ASSET_VERIFICATION:
        if item.live_supported:
            violations.append(f"{item.key}: Live must remain disabled")
        if item.capability_promoted and not item.real_paper_e2e:
            violations.append(f"{item.key}: capability promoted without real Paper E2E")
        if item.real_paper_e2e and not item.product_specific_order_path:
            violations.append(f"{item.key}: Paper E2E lacks product-specific order path")
        if item.paper_market_verified:
            if not is_verified_paper_capability(
                market=item.key,
                asset_class=item.asset_class,
                broker="IBKR",
            ):
                violations.append(
                    f"{item.key}: matrix claims market verification absent from VERIFIED_CAPABILITIES"
                )
        elif item.capability_promoted:
            violations.append(f"{item.key}: promotion level is not VERIFIED_MARKET_PAPER")
    return tuple(violations)
