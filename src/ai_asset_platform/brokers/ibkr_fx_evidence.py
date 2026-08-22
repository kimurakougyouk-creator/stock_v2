"""Compose broker-only FX evidence sources for the operator checkpoint.

The normal FX module already tries live/delayed/account data. If all of those
fail, this module tries IBKR historical MIDPOINT data. Historical data is used
only as a broker-provided read-only fallback and never causes an order.
"""
from __future__ import annotations

from ai_asset_platform.brokers.ibkr_fx_historical import (
    preview_ibkr_paper_historical_fx_rate,
)
from ai_asset_platform.brokers.ibkr_fx_snapshot import (
    IbkrFxSnapshotResult,
    preview_ibkr_paper_fx_rate,
)


def resolve_ibkr_paper_fx_evidence(
    *,
    base_currency: str,
    quote_currency: str,
    timeout: float = 10.0,
) -> IbkrFxSnapshotResult:
    primary = preview_ibkr_paper_fx_rate(
        base_currency=base_currency,
        quote_currency=quote_currency,
        timeout=timeout,
    )
    if primary.ready:
        return primary

    historical = preview_ibkr_paper_historical_fx_rate(
        base_currency=base_currency,
        quote_currency=quote_currency,
        timeout=timeout,
    )
    if historical.ready:
        return IbkrFxSnapshotResult(
            connected=historical.connected,
            endpoint_port=historical.endpoint_port,
            base_currency=historical.base_currency,
            quote_currency=historical.quote_currency,
            exchange=historical.exchange,
            bid=None,
            ask=None,
            rate=historical.rate,
            source=historical.source,
            order_sent=False,
            errors=tuple(list(primary.errors) + list(historical.errors)),
        )

    return IbkrFxSnapshotResult(
        connected=primary.connected or historical.connected,
        endpoint_port=historical.endpoint_port or primary.endpoint_port,
        base_currency=base_currency.strip().upper(),
        quote_currency=quote_currency.strip().upper(),
        exchange=historical.exchange or primary.exchange,
        bid=None,
        ask=None,
        rate=None,
        source="UNAVAILABLE",
        order_sent=False,
        errors=tuple(list(primary.errors) + list(historical.errors)),
    )
