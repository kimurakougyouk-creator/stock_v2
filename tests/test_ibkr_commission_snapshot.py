from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_commission_snapshot as module


def _row(exec_id: str, commission: float = 1.25):
    return module.IbkrCommissionEvidence(
        exec_id=exec_id,
        commission=commission,
        currency="USD",
        realized_pnl=10.0,
        yield_value=None,
        yield_redemption_date=None,
    )


def test_commission_report_preserves_exec_linked_evidence():
    probe = module._CommissionSnapshotProbe()
    report = SimpleNamespace(
        execId="0001.abc.01",
        commission=1.25,
        currency="usd",
        realizedPNL=10.5,
        yield_=float("nan"),
        yieldRedemptionDate=0,
    )

    probe.commissionReport(report)

    assert probe.commissions == [
        module.IbkrCommissionEvidence(
            exec_id="0001.abc.01",
            commission=1.25,
            currency="USD",
            realized_pnl=10.5,
            yield_value=None,
            yield_redemption_date=None,
        )
    ]


def test_invalid_commission_evidence_is_rejected_without_guessing():
    probe = module._CommissionSnapshotProbe()
    probe.commissionReport(
        SimpleNamespace(
            execId="",
            commission=1.0,
            currency="USD",
            realizedPNL=0.0,
        )
    )
    probe.commissionReport(
        SimpleNamespace(
            execId="bad-commission",
            commission=float("nan"),
            currency="USD",
            realizedPNL=0.0,
        )
    )
    probe.commissionReport(
        SimpleNamespace(
            execId="bad-currency",
            commission=1.0,
            currency="",
            realizedPNL=0.0,
        )
    )

    assert probe.commissions == []
    assert len(probe.errors) == 3


def test_exact_duplicate_is_deduped_but_conflicting_duplicate_blocks_ready():
    exact = _row("exec-1")
    rows, conflicts = module._dedupe_commissions([exact, exact])
    assert rows == (exact,)
    assert conflicts == ()

    rows, conflicts = module._dedupe_commissions(
        [exact, _row("exec-1", commission=1.50)]
    )
    snapshot = module.IbkrPaperCommissionSnapshot(
        connected=True,
        endpoint_port=4002,
        commissions=rows,
        duplicate_conflicts=conflicts,
        order_sent=False,
    )
    assert snapshot.ready is False
    assert conflicts == ("conflicting commission reports for exec_id=exec-1",)


def test_match_requires_every_requested_exec_id_and_never_infers_missing_fee():
    snapshot = module.IbkrPaperCommissionSnapshot(
        connected=True,
        endpoint_port=4002,
        commissions=(_row("exec-1"),),
        order_sent=False,
    )

    result = module.match_commissions_to_exec_ids(
        snapshot,
        ["exec-1", "exec-2"],
    )

    assert result.ready is False
    assert [row.exec_id for row in result.commissions] == ["exec-1"]
    assert result.missing_exec_ids == ("exec-2",)
    assert "missing commission evidence for broker execution IDs" in result.blockers


def test_matching_complete_exec_set_is_ready():
    snapshot = module.IbkrPaperCommissionSnapshot(
        connected=True,
        endpoint_port=4002,
        commissions=(_row("exec-1"), _row("exec-2", commission=0.5)),
        order_sent=False,
    )

    result = module.match_commissions_to_exec_ids(
        snapshot,
        ["exec-2", "exec-1", "exec-1"],
    )

    assert result.ready is True
    assert result.missing_exec_ids == ()
    assert [row.exec_id for row in result.commissions] == ["exec-2", "exec-1"]


def test_module_is_read_only_and_contains_no_order_mutation_api():
    source = Path(
        "src/ai_asset_platform/brokers/ibkr_commission_snapshot.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "transmit_ibkr_paper_order",
        "enable_live_trading = True",
        "allow_live_trading=True",
    )
    for token in forbidden:
        assert token not in source
