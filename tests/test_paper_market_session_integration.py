from __future__ import annotations

from types import SimpleNamespace

import pytest

import paper_trading_runner


def test_closed_market_blocks_before_fx_preflight_or_broker(monkeypatch):
    monkeypatch.setattr(
        paper_trading_runner,
        "evaluate_verified_market_session",
        lambda ticker: SimpleNamespace(
            allowed=False,
            reason="US verified Paper orders are allowed only during the core session",
            venue="US_CORE",
            local_timestamp="2026-09-01T03:50:00-04:00",
            session="CLOSED_OUTSIDE_CORE",
        ),
    )
    monkeypatch.setattr(
        paper_trading_runner,
        "_preflight_fx_rate",
        lambda **kwargs: pytest.fail("FX preflight must not run while market is closed"),
    )
    monkeypatch.setattr(
        paper_trading_runner,
        "evaluate_verified_paper_preflight",
        lambda **kwargs: pytest.fail("risk preflight must not run while market is closed"),
    )
    monkeypatch.setattr(
        paper_trading_runner,
        "execute_approved_signal_via_ibkr_paper",
        lambda **kwargs: pytest.fail("broker runtime must not run while market is closed"),
    )

    with pytest.raises(RuntimeError, match="market-session guard blocked order"):
        paper_trading_runner._execute_confirmed_ibkr_paper_order(
            "AAPL",
            "BUY",
            1,
            316.85,
        )
