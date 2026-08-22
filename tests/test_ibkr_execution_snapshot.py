from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_execution_snapshot as module


def test_exec_details_normalizes_broker_side_and_preserves_evidence():
    probe = module._ExecutionSnapshotProbe()
    contract = SimpleNamespace(
        symbol="spy",
        secType="STK",
        currency="USD",
        primaryExchange="ARCA",
        exchange="SMART",
    )
    execution = SimpleNamespace(
        execId="abc.1",
        orderId=3,
        permId=77,
        side="BOT",
        shares=1,
        price=765.45,
        exchange="OVERNIGHT",
        time="20260822  20:01:00 America/New_York",
        acctNumber="DU123",
    )

    probe.execDetails(992, contract, execution)

    assert probe.executions == [
        module.IbkrExecutionEvidence(
            exec_id="abc.1",
            order_id=3,
            perm_id=77,
            symbol="SPY",
            sec_type="STK",
            currency="USD",
            exchange="OVERNIGHT",
            side="BUY",
            quantity=1.0,
            price=765.45,
            time="20260822  20:01:00 America/New_York",
            account="DU123",
        )
    ]


def test_exec_details_rejects_malformed_or_nonpositive_rows():
    probe = module._ExecutionSnapshotProbe()
    contract = SimpleNamespace(symbol="SPY", secType="STK", currency="USD", exchange="SMART")
    probe.execDetails(
        992,
        contract,
        SimpleNamespace(execId="x", orderId=1, permId=2, side="BOT", shares=0, price=1),
    )
    probe.execDetails(
        992,
        contract,
        SimpleNamespace(execId="y", orderId=1, permId=2, side="UNKNOWN", shares=1, price=1),
    )
    assert probe.executions == []


def test_snapshot_ready_never_implies_order_transmission():
    snapshot = module.IbkrPaperExecutionSnapshot(
        connected=True,
        endpoint_port=4002,
        executions=(),
        order_sent=False,
        errors=(),
    )
    assert snapshot.ready is True
    assert snapshot.order_sent is False
