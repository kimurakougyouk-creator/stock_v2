from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_live_readonly_account as module


def test_missing_confirmation_blocks_before_any_live_connection(monkeypatch):
    class ExplodingProbe:
        def __init__(self):
            raise AssertionError("probe must not be created without confirmation")

    monkeypatch.setattr(module, "_AccountSnapshotProbe", ExplodingProbe)

    result = module.preview_ibkr_live_readonly_account_snapshot(
        confirmation="",
    )

    assert result.attempted is False
    assert result.connected is False
    assert result.ready is False
    assert result.blocked_reason == "exact Live read-only confirmation is missing"
    assert result.order_sent is False
    assert result.live_order_sent is False


def test_live_default_endpoint_constants_are_separate_from_paper_defaults():
    assert module.LIVE_GATEWAY_PORT == 4001
    assert module.LIVE_TWS_PORT == 7496
    assert module.LIVE_GATEWAY_PORT != 4002
    assert module.LIVE_TWS_PORT != 7497


def test_account_fingerprint_is_deterministic_and_does_not_expose_raw_id():
    raw = "U1234567"
    fingerprint = module._account_fingerprint(raw)
    assert fingerprint == module._account_fingerprint(raw)
    assert len(fingerprint) == 64
    assert raw not in fingerprint


def test_settled_cash_by_currency_uses_only_exact_currency_rows():
    probe = SimpleNamespace(
        account_values={
            ("SettledCash", "JPY"): 61000.0,
            ("SettledCash", "USD"): 125.5,
            ("SettledCash", "BASE"): 999999.0,
            ("CashBalance", "JPY"): 62000.0,
            ("SettledCash", ""): 1.0,
        }
    )
    assert module._settled_cash_by_currency(probe) == {
        "JPY": 61000.0,
        "USD": 125.5,
    }


def test_settled_cash_accepts_ibkr_ledger_prefixed_per_currency_keys():
    probe = SimpleNamespace(
        account_values={
            ("$LEDGER-SettledCash", "JPY"): 61000.0,
            ("$LEDGER-SettledCash", "USD"): 125.5,
            ("$LEDGER-SettledCash", "BASE"): 999999.0,
        }
    )
    assert module._settled_cash_by_currency(probe) == {
        "JPY": 61000.0,
        "USD": 125.5,
    }


def test_conflicting_prefixed_and_legacy_settled_cash_fails_closed_for_currency():
    probe = SimpleNamespace(
        account_values={
            ("SettledCash", "JPY"): 61000.0,
            ("$LEDGER-SettledCash", "JPY"): 60000.0,
            ("SettledCash", "USD"): 125.5,
            ("$LEDGER-SettledCash", "USD"): 125.5,
        }
    )
    assert module._settled_cash_by_currency(probe) == {"USD": 125.5}


def test_confirmed_cash_account_backfills_settled_cash_from_segment_scoped_equivalent():
    probe = SimpleNamespace(
        account_values={
            ("TotalCashValue-S", "JPY"): 20000.0,
            ("EquityWithLoanValue-S", "JPY"): 20000.0,
            ("AvailableFunds", "JPY"): 20000.0,
        },
        summary_text_values={("TradingType-S", ""): "STKCASH"},
        portfolio=[],
    )
    assert module._settled_cash_by_currency(probe) == {"JPY": 20000.0}


def test_margin_account_never_backfills_settled_cash():
    probe = SimpleNamespace(
        account_values={
            ("TotalCashValue-S", "JPY"): 20000.0,
            ("EquityWithLoanValue-S", "JPY"): 20000.0,
        },
        summary_text_values={("TradingType-S", ""): "STKMRGN"},
        portfolio=[],
    )
    assert module._settled_cash_by_currency(probe) == {}


def test_unknown_trading_type_never_backfills_settled_cash():
    probe = SimpleNamespace(
        account_values={
            ("TotalCashValue-S", "JPY"): 20000.0,
            ("EquityWithLoanValue-S", "JPY"): 20000.0,
        },
        summary_text_values={},
        portfolio=[],
    )
    assert module._settled_cash_by_currency(probe) == {}


def test_open_position_blocks_the_cash_account_backfill():
    probe = SimpleNamespace(
        account_values={
            ("TotalCashValue-S", "JPY"): 20000.0,
            ("EquityWithLoanValue-S", "JPY"): 20000.0,
        },
        summary_text_values={("TradingType-S", ""): "STKCASH"},
        portfolio=[object()],
    )
    assert module._settled_cash_by_currency(probe) == {}


def test_cash_account_backfill_never_overrides_a_real_settled_cash_value():
    probe = SimpleNamespace(
        account_values={
            ("SettledCash", "JPY"): 5000.0,
            ("TotalCashValue-S", "JPY"): 20000.0,
            ("EquityWithLoanValue-S", "JPY"): 20000.0,
        },
        summary_text_values={("TradingType-S", ""): "STKCASH"},
        portfolio=[],
    )
    assert module._settled_cash_by_currency(probe) == {"JPY": 5000.0}


def test_cash_account_backfill_fails_closed_on_conflicting_equivalent_values():
    probe = SimpleNamespace(
        account_values={
            ("TotalCashValue-S", "JPY"): 20000.0,
            ("EquityWithLoanValue-S", "JPY"): 19999.0,
        },
        summary_text_values={("TradingType-S", ""): "STKCASH"},
        portfolio=[],
    )
    assert module._settled_cash_by_currency(probe) == {}


def test_cash_account_backfill_never_resurrects_a_conflicting_settled_cash_currency():
    probe = SimpleNamespace(
        account_values={
            ("SettledCash", "JPY"): 61000.0,
            ("$LEDGER-SettledCash", "JPY"): 60000.0,
            ("TotalCashValue-S", "JPY"): 20000.0,
            ("EquityWithLoanValue-S", "JPY"): 20000.0,
        },
        summary_text_values={("TradingType-S", ""): "STKCASH"},
        portfolio=[],
    )
    assert module._settled_cash_by_currency(probe) == {}


def test_cash_account_backfill_never_resurrects_an_invalid_nonnumeric_settled_cash():
    probe = SimpleNamespace(
        account_values={
            ("TotalCashValue-S", "JPY"): 20000.0,
            ("EquityWithLoanValue-S", "JPY"): 20000.0,
        },
        account_text_values={("SettledCash", "JPY"): "-"},
        summary_text_values={("TradingType-S", ""): "STKCASH"},
        portfolio=[],
    )
    assert module._settled_cash_by_currency(probe) == {}


def test_currencies_observed_under_keys_includes_nonnumeric_observations():
    probe = SimpleNamespace(
        account_values={},
        account_text_values={("SettledCash", "JPY"): "nan"},
    )
    assert module._currencies_observed_under_keys(probe, module._SETTLED_CASH_KEYS) == {"JPY"}


def test_currencies_observed_under_keys_includes_blank_observations():
    probe = SimpleNamespace(
        account_values={},
        account_text_values={("SettledCash", "JPY"): ""},
    )
    assert module._currencies_observed_under_keys(probe, module._SETTLED_CASH_KEYS) == {"JPY"}


def test_cash_account_backfill_never_resurrects_a_blank_invalidated_settled_cash():
    probe = SimpleNamespace(
        account_values={
            ("TotalCashValue-S", "JPY"): 20000.0,
            ("EquityWithLoanValue-S", "JPY"): 20000.0,
        },
        account_text_values={("SettledCash", "JPY"): ""},
        summary_text_values={("TradingType-S", ""): "STKCASH"},
        portfolio=[],
    )
    assert module._settled_cash_by_currency(probe) == {}


def test_segment_trading_type_is_read_fresh_and_not_inferred():
    assert module._segment_trading_type(SimpleNamespace()) is None
    assert (
        module._segment_trading_type(
            SimpleNamespace(summary_text_values={("TradingType-S", ""): "stkcash"})
        )
        == "STKCASH"
    )
    assert (
        module._segment_trading_type(
            SimpleNamespace(summary_text_values={("TradingType-S", ""): ""})
        )
        is None
    )


def test_segment_trading_type_checks_both_summary_and_account_update_paths():
    assert (
        module._segment_trading_type(
            SimpleNamespace(account_text_values={("TradingType-S", ""): "STKCASH"})
        )
        == "STKCASH"
    )
    assert (
        module._segment_trading_type(
            SimpleNamespace(
                summary_text_values={("TradingType-S", ""): "STKCASH"},
                account_text_values={("TradingType-S", ""): "STKCASH"},
            )
        )
        == "STKCASH"
    )


def test_segment_trading_type_is_unconfirmed_when_the_two_paths_disagree():
    probe = SimpleNamespace(
        summary_text_values={("TradingType-S", ""): "STKCASH"},
        account_text_values={("TradingType-S", ""): "STKMRGN"},
    )
    assert module._segment_trading_type(probe) is None


def test_nonfinite_settled_cash_is_never_accepted():
    probe = SimpleNamespace(
        account_values={
            ("SettledCash", "JPY"): float("nan"),
            ("$LEDGER-SettledCash", "USD"): float("inf"),
        }
    )
    assert module._settled_cash_by_currency(probe) == {}


def test_ready_requires_complete_live_readonly_evidence():
    ready = module.IbkrLiveReadOnlyAccountSnapshot(
        attempted=True,
        connected=True,
        endpoint_port=4001,
        account_fingerprint="a" * 64,
        account_ready=True,
        base_currency="JPY",
        net_liquidation=100000.0,
        available_funds=100000.0,
        gross_position_value=0.0,
        total_cash_value=100000.0,
        settled_cash_by_currency={"JPY": 100000.0},
        positions=(),
        blocked_reason=None,
        order_sent=False,
        live_order_sent=False,
    )
    assert ready.ready is True

    incomplete = module.IbkrLiveReadOnlyAccountSnapshot(
        attempted=True,
        connected=True,
        endpoint_port=4001,
        account_fingerprint="a" * 64,
        account_ready=True,
        base_currency="JPY",
        net_liquidation=None,
        available_funds=None,
        gross_position_value=None,
        total_cash_value=None,
        settled_cash_by_currency={},
        positions=(),
        blocked_reason=None,
        order_sent=False,
        live_order_sent=False,
    )
    assert incomplete.ready is False


def test_module_contains_no_order_or_live_unlock_api():
    source = Path(
        "src/ai_asset_platform/brokers/ibkr_live_readonly_account.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "transmit_ibkr",
        "enable_live_trading = True",
        "allow_live_trading=True",
        "RUN_MODE=LIVE",
    )
    for token in forbidden:
        assert token not in source
