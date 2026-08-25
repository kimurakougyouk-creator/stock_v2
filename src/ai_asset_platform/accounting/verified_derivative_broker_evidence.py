"""Immutable broker execution evidence already observed in IBKR Paper.

These rows are not synthetic trades. They are a durable copy of execution
identity/price facts previously returned by the broker during verified Paper
round-trips. They are used only when the broker's current reqExecutions history
window no longer returns the older fills. Current broker flatness must still be
verified separately before an audit can pass.
"""
from __future__ import annotations

from ai_asset_platform.brokers.ibkr_execution_snapshot import IbkrExecutionEvidence


VERIFIED_ESU6_EXECUTIONS = (
    IbkrExecutionEvidence(
        exec_id="0000e1a7.6a8f948c.01.01",
        order_id=1,
        perm_id=0,
        symbol="ES",
        sec_type="FUT",
        currency="USD",
        exchange="CME",
        side="BUY",
        quantity=1.0,
        price=7668.25,
        time="",
        account="",
        con_id=649180671,
        local_symbol="ESU6",
        expiry="20260918",
        multiplier="50",
    ),
    IbkrExecutionEvidence(
        exec_id="0000e1a7.6a8f948d.01.01",
        order_id=2,
        perm_id=0,
        symbol="ES",
        sec_type="FUT",
        currency="USD",
        exchange="CME",
        side="SELL",
        quantity=1.0,
        price=7667.75,
        time="",
        account="",
        con_id=649180671,
        local_symbol="ESU6",
        expiry="20260918",
        multiplier="50",
    ),
)

VERIFIED_SPY_OPTION_EXECUTIONS = (
    IbkrExecutionEvidence(
        exec_id="00020057.6a8c86b2.01.01",
        order_id=1,
        perm_id=0,
        symbol="SPY",
        sec_type="OPT",
        currency="USD",
        exchange="SMART",
        side="BUY",
        quantity=1.0,
        price=4.08,
        time="20260824 14:43:18 US/Eastern",
        account="",
        con_id=900369377,
        local_symbol="SPY   260828C00765000",
        expiry="20260828",
        multiplier="100",
    ),
    IbkrExecutionEvidence(
        exec_id="00020057.6a8c86b3.01.01",
        order_id=2,
        perm_id=0,
        symbol="SPY",
        sec_type="OPT",
        currency="USD",
        exchange="SMART",
        side="SELL",
        quantity=1.0,
        price=4.07,
        time="20260824 14:43:19 US/Eastern",
        account="",
        con_id=900369377,
        local_symbol="SPY   260828C00765000",
        expiry="20260828",
        multiplier="100",
    ),
)
