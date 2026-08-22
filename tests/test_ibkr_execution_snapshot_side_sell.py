from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_execution_snapshot as module


def test_exec_details_normalizes_sell_side():
    probe = module._ExecutionSnapshotProbe()
    contract = SimpleNamespace(symbol="SPY", secType="STK", currency="USD", exchange="SMART")
    execution = SimpleNamespace(
        execId="sell.1",
        orderId=4,
        permId=88,
        side="SLD",
        shares=1,
        price=766.0,
        exchange="ARCA",
        time="20260822  20:10:00 America/New_York",
        acctNumber="DU123",
    )
    probe.execDetails(992, contract, execution)
    assert probe.executions[0].side == "SELL"
