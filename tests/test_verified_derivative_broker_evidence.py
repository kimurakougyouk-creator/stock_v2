from decimal import Decimal

from ai_asset_platform.accounting.futures_postfill_audit import (
    _durable_verified_snapshot as futures_snapshot,
    evaluate_futures_postfill_from_existing_snapshot,
)
from ai_asset_platform.accounting.options_postfill_audit import (
    _durable_verified_snapshot as option_snapshot,
    evaluate_option_postfill_from_existing_snapshot,
)
from ai_asset_platform.accounting.verified_derivative_broker_evidence import (
    VERIFIED_ESU6_EXECUTIONS,
    VERIFIED_SPY_OPTION_EXECUTIONS,
)
from ai_asset_platform.brokers.ibkr_crypto_discovery import CRYPTO_CLIENT_OFFSETS
from ai_asset_platform.brokers.ibkr_execution_snapshot import IbkrPaperExecutionSnapshot


def _empty_ready_snapshot():
    return IbkrPaperExecutionSnapshot(True, 4002, (), False, ())


def test_verified_futures_evidence_survives_broker_history_window_expiry():
    snap = futures_snapshot(_empty_ready_snapshot(), broker_connected=True)
    assert snap.executions == VERIFIED_ESU6_EXECUTIONS
    result = evaluate_futures_postfill_from_existing_snapshot(snap, broker_flat=True)
    assert result.ready is True
    assert result.realized_pnl_usd == Decimal("-25.00")
    assert result.ending_contracts == 0
    assert result.restart_recovery_verified is True


def test_verified_option_evidence_survives_broker_history_window_expiry():
    snap = option_snapshot(_empty_ready_snapshot(), broker_connected=True)
    assert snap.executions == VERIFIED_SPY_OPTION_EXECUTIONS
    result = evaluate_option_postfill_from_existing_snapshot(snap, broker_flat=True)
    assert result.ready is True
    assert result.realized_pnl_usd == Decimal("-1.00")
    assert result.ending_contracts == 0
    assert result.restart_recovery_verified is True


def test_persisted_evidence_cannot_pass_without_current_broker_connection():
    futures = futures_snapshot(_empty_ready_snapshot(), broker_connected=False)
    options = option_snapshot(_empty_ready_snapshot(), broker_connected=False)
    assert evaluate_futures_postfill_from_existing_snapshot(futures, broker_flat=False).ready is False
    assert evaluate_option_postfill_from_existing_snapshot(options, broker_flat=False).ready is False


def test_crypto_venues_use_distinct_read_only_client_ids():
    assert CRYPTO_CLIENT_OFFSETS["PAXOS"] != CRYPTO_CLIENT_OFFSETS["ZEROHASH"]
