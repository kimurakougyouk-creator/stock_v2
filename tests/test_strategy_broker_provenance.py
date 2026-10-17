from __future__ import annotations

from ai_asset_platform.brokers.ibkr_commission_snapshot import (
    IbkrCommissionEvidence,
    IbkrPaperCommissionSnapshot,
)
from ai_asset_platform.brokers.ibkr_completed_order_evidence import (
    IbkrCompletedOrderEvidence,
    IbkrPaperCompletedOrderSnapshot,
)
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
)
from ai_asset_platform.execution.strategy_broker_provenance import (
    verify_broker_provenance_for_strategy_fills,
)


DEFAULT_EXEC_TIME = "20261016 09:00:00 Asia/Tokyo"
DEFAULT_CREATED_AT = "2026-10-16T09:00:00+09:00"
DEFAULT_INTENT_ID = "signal-runner:9432.T:BUY:100:2026-10-16T09:00:00+09:00"


def _execution(**overrides) -> IbkrExecutionEvidence:
    base = dict(
        exec_id="exec-1",
        order_id=1,
        perm_id=100,
        symbol="9432",
        sec_type="STK",
        currency="JPY",
        exchange="TSEJ",
        side="BUY",
        quantity=100.0,
        price=172.1,
        time=DEFAULT_EXEC_TIME,
        account="DU0000001",
    )
    base.update(overrides)
    return IbkrExecutionEvidence(**base)


def _commission(**overrides) -> IbkrCommissionEvidence:
    base = dict(
        exec_id="exec-1",
        commission=80.0,
        currency="JPY",
        realized_pnl=None,
        yield_value=None,
        yield_redemption_date=None,
    )
    base.update(overrides)
    return IbkrCommissionEvidence(**base)


def _fill(**overrides) -> dict:
    base = dict(
        ticker="9432.T",
        side="BUY",
        shares=100,
        currency="JPY",
        reference_price=172.1,
        created_at=DEFAULT_CREATED_AT,
        order_intent_id=DEFAULT_INTENT_ID,
        broker_exec_fills=[{"exec_id": "exec-1", "shares": 100}],
    )
    base.update(overrides)
    return base


def _execution_snapshot(*rows: IbkrExecutionEvidence, ready: bool = True) -> IbkrPaperExecutionSnapshot:
    return IbkrPaperExecutionSnapshot(
        connected=ready,
        endpoint_port=4002 if ready else None,
        executions=tuple(rows),
        order_sent=False,
        errors=(),
    )


def _commission_snapshot(*rows: IbkrCommissionEvidence, ready: bool = True) -> IbkrPaperCommissionSnapshot:
    return IbkrPaperCommissionSnapshot(
        connected=ready,
        endpoint_port=4002 if ready else None,
        commissions=tuple(rows),
        duplicate_conflicts=(),
        order_sent=False,
        errors=(),
    )


def _completed_order(**overrides) -> IbkrCompletedOrderEvidence:
    base = dict(
        order_id=1,
        perm_id=100,
        symbol="9432",
        sec_type="STK",
        currency="JPY",
        exchange="TSEJ",
        action="BUY",
        quantity=100.0,
        order_type="LMT",
        limit_price=172.1,
        status="Filled",
        completed_time=DEFAULT_EXEC_TIME,
        completed_status="",
        account="DU0000001",
        order_ref=DEFAULT_INTENT_ID,
    )
    base.update(overrides)
    return IbkrCompletedOrderEvidence(**base)


def _completed_order_snapshot(
    *rows: IbkrCompletedOrderEvidence, ready: bool = True
) -> IbkrPaperCompletedOrderSnapshot:
    return IbkrPaperCompletedOrderSnapshot(
        connected=ready,
        endpoint_port=4002 if ready else None,
        orders=tuple(rows),
        order_sent=False,
        errors=(),
    )


def _local_commission_report(*rows: dict) -> dict:
    return {
        "schema_version": 1,
        "paper_only": True,
        "order_sent": False,
        "live_order_sent": False,
        "commissions": list(rows),
    }


def _local_commission(exec_id: str = "exec-1", commission: float = 80.0, currency: str = "JPY") -> dict:
    return {"exec_id": exec_id, "commission": commission, "currency": currency}


def _unused_fx_fetcher(*args):
    raise AssertionError(
        "fx_rate_fetcher must not be called for a same-currency (non-foreign) fill"
    )


def _fixed_fx_fetcher(rate: float | None):
    def _fetch(base_currency, quote_currency, reference_timestamp, end_datetime):
        return rate

    return _fetch


def _verify(
    fills,
    *,
    account_currency="JPY",
    fx_rate_fetcher=_unused_fx_fetcher,
    completed_order_snapshot=None,
    **snapshots,
):
    if completed_order_snapshot is None:
        completed_order_snapshot = _completed_order_snapshot(_completed_order())
    return verify_broker_provenance_for_strategy_fills(
        fills,
        account_currency=account_currency,
        fx_rate_fetcher=fx_rate_fetcher,
        completed_order_snapshot=completed_order_snapshot,
        **snapshots,
    )


def test_matching_broker_evidence_verifies_provenance():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is True
    assert result.blockers == ()
    assert result.verified_fill_count == 1
    assert result.total_fill_count == 1


def test_not_ready_execution_snapshot_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution(), ready=False),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert "execution snapshot is not ready" in result.blockers[0]


def test_not_ready_commission_snapshot_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission(), ready=False),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert "commission snapshot is not ready" in result.blockers[0]


def test_missing_exec_id_in_broker_execution_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert any("was not found in the broker execution snapshot" in b for b in result.blockers)


def test_symbol_mismatch_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution(symbol="AAPL")),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert any("identity does not match the local fill" in b for b in result.blockers)


def test_side_mismatch_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution(side="SELL")),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert any("identity does not match the local fill" in b for b in result.blockers)


def test_quantity_mismatch_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution(quantity=50.0)),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert any("broker quantity does not match the local quantity" in b for b in result.blockers)


def test_missing_commission_evidence_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert any("missing broker commission evidence" in b for b in result.blockers)


def test_commission_currency_mismatch_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission(currency="USD")),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert any("commission currency does not match the fill" in b for b in result.blockers)


def test_broker_execution_price_mismatch_fails_closed():
    # Regression for Codex P1 finding on PR #350: a locally-edited
    # reference_price must not silently pass just because exec_id/quantity
    # still line up with the broker execution.
    result = _verify(
        [_fill(reference_price=999.0)],
        execution_snapshot=_execution_snapshot(_execution(price=172.1)),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert any(
        "weighted average execution price does not match the local reference_price" in b
        for b in result.blockers
    )


def test_broker_commission_amount_mismatch_fails_closed():
    # Regression for Codex P1 finding on PR #350: a locally-edited commission
    # amount (same exec_id/currency) must not silently pass.
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission(commission=80.0)),
        local_commission_report=_local_commission_report(
            _local_commission(commission=5.0)
        ),
    )
    assert result.verified is False
    assert any(
        "broker commission amount does not match the local commission ledger" in b
        for b in result.blockers
    )


def test_missing_local_commission_entry_for_exec_id_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(),
    )
    assert result.verified is False
    assert any(
        "no local commission ledger entry to cross-check" in b for b in result.blockers
    )


def test_missing_local_commission_report_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=None,
    )
    assert result.verified is False
    assert any("local commission ledger is unreadable" in b for b in result.blockers)


def test_malformed_local_commission_report_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report={"not": "a valid ledger"},
    )
    assert result.verified is False
    assert any("local commission ledger is unreadable" in b for b in result.blockers)


def test_multiple_execution_rows_summing_to_total_shares_verifies():
    fill = _fill(
        shares=100,
        reference_price=172.0,
        broker_exec_fills=[
            {"exec_id": "exec-1", "shares": 60},
            {"exec_id": "exec-2", "shares": 40},
        ],
    )
    result = _verify(
        [fill],
        execution_snapshot=_execution_snapshot(
            _execution(exec_id="exec-1", quantity=60.0, price=172.0),
            _execution(exec_id="exec-2", quantity=40.0, price=172.0),
        ),
        commission_snapshot=_commission_snapshot(
            _commission(exec_id="exec-1", commission=48.0),
            _commission(exec_id="exec-2", commission=32.0),
        ),
        local_commission_report=_local_commission_report(
            _local_commission(exec_id="exec-1", commission=48.0),
            _local_commission(exec_id="exec-2", commission=32.0),
        ),
    )
    assert result.verified is True
    assert result.verified_fill_count == 1


def test_multi_leg_weighted_average_price_must_match_reference_price():
    # 60 shares @ 170.0 + 40 shares @ 175.0 -> weighted avg = 172.0
    fill = _fill(
        shares=100,
        reference_price=172.0,
        broker_exec_fills=[
            {"exec_id": "exec-1", "shares": 60},
            {"exec_id": "exec-2", "shares": 40},
        ],
    )
    result = _verify(
        [fill],
        execution_snapshot=_execution_snapshot(
            _execution(exec_id="exec-1", quantity=60.0, price=170.0),
            _execution(exec_id="exec-2", quantity=40.0, price=175.0),
        ),
        commission_snapshot=_commission_snapshot(
            _commission(exec_id="exec-1", commission=48.0),
            _commission(exec_id="exec-2", commission=32.0),
        ),
        local_commission_report=_local_commission_report(
            _local_commission(exec_id="exec-1", commission=48.0),
            _local_commission(exec_id="exec-2", commission=32.0),
        ),
    )
    assert result.verified is True


def test_partial_execution_rows_not_summing_to_total_shares_fails_closed():
    fill = _fill(
        shares=100,
        broker_exec_fills=[{"exec_id": "exec-1", "shares": 60}],
    )
    result = _verify(
        [fill],
        execution_snapshot=_execution_snapshot(_execution(exec_id="exec-1", quantity=60.0)),
        commission_snapshot=_commission_snapshot(_commission(exec_id="exec-1", commission=48.0)),
        local_commission_report=_local_commission_report(
            _local_commission(exec_id="exec-1", commission=48.0)
        ),
    )
    assert result.verified is False
    assert any("matched broker quantity does not equal" in b for b in result.blockers)


def test_no_fills_supplied_fails_closed():
    result = _verify(
        [],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert result.blockers == ("no natural strategy fills were supplied",)
    assert result.total_fill_count == 0


def test_missing_created_at_fails_closed():
    result = _verify(
        [_fill(created_at=None)],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert any(
        "missing a valid timezone-aware created_at" in b for b in result.blockers
    )


def test_naive_created_at_without_timezone_fails_closed():
    result = _verify(
        [_fill(created_at="2026-10-16T09:00:00")],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert any(
        "missing a valid timezone-aware created_at" in b for b in result.blockers
    )


def test_local_created_at_far_from_broker_execution_time_fails_closed():
    # Regression for Codex P1 finding on PR #350: a locally-edited created_at
    # must not silently pass even though exec_id/qty/price/commission match.
    result = _verify(
        [_fill(created_at="2026-10-20T09:00:00+09:00")],  # 4 days away
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert any(
        "does not match the broker execution time within tolerance" in b
        for b in result.blockers
    )


def test_local_created_at_within_tolerance_of_broker_execution_time_verifies():
    result = _verify(
        [_fill(created_at="2026-10-16T09:02:00+09:00")],  # 120s after exec
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is True


def test_foreign_currency_fill_matching_broker_fx_rate_verifies():
    result = _verify(
        [
            _fill(
                ticker="AAPL",
                currency="USD",
                fx_to_account_rate=150.0,
            )
        ],
        execution_snapshot=_execution_snapshot(_execution(symbol="AAPL", currency="USD")),
        commission_snapshot=_commission_snapshot(_commission(currency="USD")),
        local_commission_report=_local_commission_report(
            _local_commission(currency="USD")
        ),
        account_currency="JPY",
        fx_rate_fetcher=_fixed_fx_fetcher(150.0),
    )
    assert result.verified is True


def test_foreign_currency_fill_fx_rate_mismatch_fails_closed():
    # Regression for Codex P1 finding on PR #350: an edited local
    # fx_to_account_rate must not silently pass.
    result = _verify(
        [
            _fill(
                ticker="AAPL",
                currency="USD",
                fx_to_account_rate=999.0,
            )
        ],
        execution_snapshot=_execution_snapshot(_execution(symbol="AAPL", currency="USD")),
        commission_snapshot=_commission_snapshot(_commission(currency="USD")),
        local_commission_report=_local_commission_report(
            _local_commission(currency="USD")
        ),
        account_currency="JPY",
        fx_rate_fetcher=_fixed_fx_fetcher(150.0),
    )
    assert result.verified is False
    assert any(
        "fx_to_account_rate does not match the independently fetched broker FX rate" in b
        for b in result.blockers
    )


def test_foreign_currency_fill_missing_broker_fx_evidence_fails_closed():
    result = _verify(
        [
            _fill(
                ticker="AAPL",
                currency="USD",
                fx_to_account_rate=150.0,
            )
        ],
        execution_snapshot=_execution_snapshot(_execution(symbol="AAPL", currency="USD")),
        commission_snapshot=_commission_snapshot(_commission(currency="USD")),
        local_commission_report=_local_commission_report(
            _local_commission(currency="USD")
        ),
        account_currency="JPY",
        fx_rate_fetcher=_fixed_fx_fetcher(None),
    )
    assert result.verified is False
    assert any(
        "independent broker FX evidence" in b and "unavailable" in b
        for b in result.blockers
    )


def test_same_currency_fill_never_calls_fx_rate_fetcher():
    # account_currency == fill currency (JPY/JPY): the FX check must be
    # skipped entirely. _unused_fx_fetcher raises if ever invoked.
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is True


def test_missing_order_intent_id_fails_closed():
    result = _verify(
        [_fill(order_intent_id="")],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
    )
    assert result.verified is False
    assert any("missing order_intent_id" in b for b in result.blockers)


def test_not_ready_completed_order_snapshot_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
        completed_order_snapshot=_completed_order_snapshot(_completed_order(), ready=False),
    )
    assert result.verified is False
    assert "completed-order snapshot is not ready" in result.blockers[0]


def test_missing_completed_order_evidence_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
        completed_order_snapshot=_completed_order_snapshot(),
    )
    assert result.verified is False
    assert any(
        "no matching broker completed-order evidence" in b for b in result.blockers
    )


def test_order_ref_mismatch_fails_closed():
    # Regression for Codex P1 finding on PR #350: an unrelated real Paper
    # trade relabeled locally with a signal-runner: intent must not pass
    # just because its other fields happen to match the broker snapshot.
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
        completed_order_snapshot=_completed_order_snapshot(
            _completed_order(order_ref="some-unrelated-manual-proof-trade")
        ),
    )
    assert result.verified is False
    assert any(
        "orderRef does not match the local order_intent_id" in b
        for b in result.blockers
    )


def test_order_ref_empty_fails_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
        completed_order_snapshot=_completed_order_snapshot(
            _completed_order(order_ref="")
        ),
    )
    assert result.verified is False
    assert any(
        "orderRef does not match the local order_intent_id" in b
        for b in result.blockers
    )


def test_order_ref_matching_local_intent_verifies():
    result = _verify(
        [_fill(order_intent_id="signal-runner:9432.T:BUY:100:bar-key-x")],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
        completed_order_snapshot=_completed_order_snapshot(
            _completed_order(order_ref="signal-runner:9432.T:BUY:100:bar-key-x")
        ),
    )
    assert result.verified is True


def test_multi_leg_fill_matches_the_same_order_ref_for_both_executions():
    fill = _fill(
        shares=100,
        reference_price=172.0,
        broker_exec_fills=[
            {"exec_id": "exec-1", "shares": 60},
            {"exec_id": "exec-2", "shares": 40},
        ],
    )
    result = _verify(
        [fill],
        execution_snapshot=_execution_snapshot(
            _execution(exec_id="exec-1", quantity=60.0, price=172.0),
            _execution(exec_id="exec-2", quantity=40.0, price=172.0),
        ),
        commission_snapshot=_commission_snapshot(
            _commission(exec_id="exec-1", commission=48.0),
            _commission(exec_id="exec-2", commission=32.0),
        ),
        local_commission_report=_local_commission_report(
            _local_commission(exec_id="exec-1", commission=48.0),
            _local_commission(exec_id="exec-2", commission=32.0),
        ),
        completed_order_snapshot=_completed_order_snapshot(_completed_order()),
    )
    assert result.verified is True


def test_conflicting_completed_order_rows_for_same_perm_id_fail_closed():
    result = _verify(
        [_fill()],
        execution_snapshot=_execution_snapshot(_execution()),
        commission_snapshot=_commission_snapshot(_commission()),
        local_commission_report=_local_commission_report(_local_commission()),
        completed_order_snapshot=_completed_order_snapshot(
            _completed_order(order_ref=DEFAULT_INTENT_ID),
            _completed_order(order_ref="different-intent"),
        ),
    )
    assert result.verified is False
    assert any(
        "conflicting broker completed-order rows" in b for b in result.blockers
    )


def test_module_contains_no_order_transport():
    from pathlib import Path

    source = Path(
        "src/ai_asset_platform/execution/strategy_broker_provenance.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "LIVE_GATEWAY_PORT",
        "LIVE_TWS_PORT",
        "allow_live_trading=True",
    )
    for token in forbidden:
        assert token not in source
