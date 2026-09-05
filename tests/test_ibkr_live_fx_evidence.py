from __future__ import annotations

from pathlib import Path

from ai_asset_platform.brokers.ibkr_fx_snapshot import IbkrFxSnapshotResult
import ai_asset_platform.brokers.ibkr_live_fx_evidence as module


def test_missing_confirmation_blocks_before_live_request(monkeypatch):
    monkeypatch.setattr(
        module,
        "_request_live_market_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Live request must not start without confirmation")
        ),
    )

    result = module.resolve_ibkr_live_fx_evidence(
        base_currency="USD",
        quote_currency="JPY",
        confirmation="",
    )

    assert result.ready is False
    assert result.source == "BLOCKED"
    assert result.order_sent is False


def test_same_currency_identity_needs_no_broker_request(monkeypatch):
    monkeypatch.setattr(
        module,
        "_request_live_market_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("identity FX must not open broker socket")
        ),
    )

    result = module.resolve_ibkr_live_fx_evidence(
        base_currency="JPY",
        quote_currency="JPY",
        confirmation=module.CONFIRMATION_VALUE,
    )

    assert result.ready is True
    assert result.rate == 1.0
    assert result.source == "IDENTITY"


def test_live_market_data_is_preferred_over_account_fallback(monkeypatch):
    seen: list[int] = []

    def market(**kwargs):
        seen.append(kwargs["market_data_type"])
        if kwargs["market_data_type"] == 3:
            return IbkrFxSnapshotResult(
                connected=True,
                endpoint_port=4001,
                base_currency="USD",
                quote_currency="JPY",
                exchange="IDEALPRO",
                bid=150.0,
                ask=150.2,
                rate=150.1,
                source="LIVE_SESSION_DELAYED_MARKET_DATA",
                order_sent=False,
                errors=(),
            )
        return IbkrFxSnapshotResult(
            connected=False,
            endpoint_port=None,
            base_currency="USD",
            quote_currency="JPY",
            exchange="IDEALPRO",
            bid=None,
            ask=None,
            rate=None,
            source="NO_DATA",
            order_sent=False,
            errors=("unavailable",),
        )

    monkeypatch.setattr(module, "_request_live_market_snapshot", market)
    monkeypatch.setattr(
        module,
        "_request_live_account_fx",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("account fallback must not run after valid market rate")
        ),
    )

    result = module.resolve_ibkr_live_fx_evidence(
        base_currency="USD",
        quote_currency="JPY",
        confirmation=module.CONFIRMATION_VALUE,
    )

    assert seen == [1, 3]
    assert result.ready is True
    assert result.rate == 150.1
    assert result.endpoint_port == 4001


def test_missing_market_data_uses_live_account_exchange_rate(monkeypatch):
    monkeypatch.setattr(
        module,
        "_request_live_market_snapshot",
        lambda **kwargs: IbkrFxSnapshotResult(
            connected=False,
            endpoint_port=None,
            base_currency="USD",
            quote_currency="JPY",
            exchange="IDEALPRO",
            bid=None,
            ask=None,
            rate=None,
            source="NO_DATA",
            order_sent=False,
            errors=("no quote",),
        ),
    )
    monkeypatch.setattr(
        module,
        "_request_live_account_fx",
        lambda **kwargs: IbkrFxSnapshotResult(
            connected=True,
            endpoint_port=4001,
            base_currency="USD",
            quote_currency="JPY",
            exchange="ACCOUNT",
            bid=None,
            ask=None,
            rate=149.8,
            source="LIVE_ACCOUNT_EXCHANGE_RATE",
            order_sent=False,
            errors=(),
        ),
    )

    result = module.resolve_ibkr_live_fx_evidence(
        base_currency="USD",
        quote_currency="JPY",
        confirmation=module.CONFIRMATION_VALUE,
    )

    assert result.ready is True
    assert result.rate == 149.8
    assert result.source == "LIVE_ACCOUNT_EXCHANGE_RATE"


def test_module_contains_no_order_mutation_or_preview_api():
    source = Path(
        "src/ai_asset_platform/brokers/ibkr_live_fx_evidence.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "whatIf=True",
        "transmit_ibkr",
        "enable_live_trading = True",
    )
    for token in forbidden:
        assert token not in source


def test_live_ports_remain_distinct_from_paper_ports():
    assert module.LIVE_GATEWAY_PORT == 4001
    assert module.LIVE_TWS_PORT == 7496
