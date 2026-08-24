import pytest

from ai_asset_platform.reports.paired_spy_close_accounting import (
    PairedSpyCloseAccountingError,
    enrich_closed_spy_round_trip,
)


def _buy():
    return {
        "mode": "IBKR_PAPER", "status": "FILLED", "ticker": "SPY",
        "side": "BUY", "shares": 1, "reference_price": 765.45,
        "currency": "USD", "order_intent_id": "broker-recovery:buy",
        "broker_exec_ids": ["BUY_EXEC"],
    }


def _sell():
    return {
        "mode": "IBKR_PAPER", "status": "FILLED", "ticker": "SPY",
        "side": "SELL", "shares": 1, "reference_price": 766.34,
        "currency": "USD", "order_intent_id": "overnight-close",
        "broker_exec_ids": ["SELL_EXEC"], "fx_to_account_rate": 158.8725,
    }


def test_enriches_only_exact_closed_spy_pair():
    rows = [_buy(), _sell()]
    enriched = enrich_closed_spy_round_trip(rows)
    assert "fx_to_account_rate" not in rows[0]
    assert enriched[0]["fx_to_account_rate"] == 158.8725
    assert enriched[0]["fx_accounting_source"] == "paired-close-sell-explicit-fx"


def test_does_not_guess_without_sell_fx():
    sell = _sell()
    sell.pop("fx_to_account_rate")
    enriched = enrich_closed_spy_round_trip([_buy(), sell])
    assert "fx_to_account_rate" not in enriched[0]


def test_rejects_overlapping_broker_execution_identity():
    sell = _sell()
    sell["broker_exec_ids"] = ["BUY_EXEC"]
    with pytest.raises(PairedSpyCloseAccountingError):
        enrich_closed_spy_round_trip([_buy(), sell])
