"""Compose broker-only FX evidence for Paper risk/accounting.

The chain intentionally uses only documented broker read paths:
1. live CASH/IDEALPRO bid/ask,
2. delayed market data,
3. delayed-frozen market data,
4. historical CASH/IDEALPRO MIDPOINT,
5. legacy account-updates ExchangeRate.

`reqAccountSummary(..., "ExchangeRate")` is deliberately not used because
ExchangeRate is not a documented AccountSummary tag. No path creates, changes,
cancels, or transmits an order. Missing evidence fails closed.
"""
from __future__ import annotations

from ai_asset_platform.brokers.ibkr_fx_discovery import build_fx_discovery_contract
from ai_asset_platform.brokers.ibkr_fx_historical import (
    preview_ibkr_paper_historical_fx_rate,
)
from ai_asset_platform.brokers.ibkr_fx_snapshot import (
    IbkrFxSnapshotResult,
    _request_market_snapshot,
    preview_ibkr_paper_account_fx_rate,
)


def _with_errors(result: IbkrFxSnapshotResult, prior_errors: list[str]) -> IbkrFxSnapshotResult:
    return IbkrFxSnapshotResult(
        connected=result.connected,
        endpoint_port=result.endpoint_port,
        base_currency=result.base_currency,
        quote_currency=result.quote_currency,
        exchange=result.exchange,
        bid=result.bid,
        ask=result.ask,
        rate=result.rate,
        source=result.source,
        order_sent=False,
        errors=tuple(prior_errors + list(result.errors)),
    )


def resolve_ibkr_paper_fx_evidence(
    *,
    base_currency: str,
    quote_currency: str,
    timeout: float = 10.0,
) -> IbkrFxSnapshotResult:
    """Resolve explicit broker FX evidence without guessing or order activity."""
    base = str(base_currency).strip().upper()
    quote = str(quote_currency).strip().upper()
    if len(base) != 3 or len(quote) != 3 or not base.isalpha() or not quote.isalpha():
        return IbkrFxSnapshotResult(
            connected=False,
            endpoint_port=None,
            base_currency=base,
            quote_currency=quote,
            exchange="UNAVAILABLE",
            bid=None,
            ask=None,
            rate=None,
            source="UNAVAILABLE",
            order_sent=False,
            errors=("invalid 3-letter currency code",),
        )
    if base == quote:
        return IbkrFxSnapshotResult(
            connected=True,
            endpoint_port=None,
            base_currency=base,
            quote_currency=quote,
            exchange="IDENTITY",
            bid=1.0,
            ask=1.0,
            rate=1.0,
            source="IDENTITY",
            order_sent=False,
            errors=(),
        )

    contract = build_fx_discovery_contract(
        base_currency=base,
        quote_currency=quote,
        exchange="IDEALPRO",
    )
    errors: list[str] = []

    for market_data_type in (1, 3, 4):
        market = _request_market_snapshot(
            contract,
            market_data_type=market_data_type,
            timeout=timeout,
        )
        if market.ready:
            return _with_errors(market, errors)
        errors.extend(market.errors)

    historical = preview_ibkr_paper_historical_fx_rate(
        base_currency=base,
        quote_currency=quote,
        exchange="IDEALPRO",
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
            errors=tuple(errors + list(historical.errors)),
        )
    errors.extend(historical.errors)

    account = preview_ibkr_paper_account_fx_rate(
        base_currency=base,
        quote_currency=quote,
        timeout=timeout,
    )
    if account.ready:
        return _with_errors(account, errors)
    errors.extend(account.errors)

    return IbkrFxSnapshotResult(
        connected=historical.connected or account.connected,
        endpoint_port=account.endpoint_port or historical.endpoint_port,
        base_currency=base,
        quote_currency=quote,
        exchange="UNAVAILABLE",
        bid=None,
        ask=None,
        rate=None,
        source="UNAVAILABLE",
        order_sent=False,
        errors=tuple(errors),
    )
