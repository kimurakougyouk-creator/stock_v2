from ai_asset_platform.brokers.ibkr_etf_audit import IbkrEtfAuditResult
from ai_asset_platform.brokers.ibkr_overnight_audit import IbkrOvernightAuditResult
from ai_asset_platform.brokers.ibkr_us_market_readonly_audit import (
    IbkrUsMarketReadonlyAuditResult,
    run_ibkr_us_market_readonly_audit,
)


def etf_result(*, connected=True, resolved=True, sent=False):
    return IbkrEtfAuditResult(
        connected,
        resolved,
        "SPY",
        "STK" if resolved else None,
        "SMART" if resolved else None,
        "USD" if resolved else None,
        sent,
        "test",
    )


def overnight_result(*, connected=True, base=True, ready=True, sent=False):
    return IbkrOvernightAuditResult(
        connected,
        base,
        ready,
        "SPY",
        "ARCA" if ready else None,
        "OVERNIGHT" if ready else None,
        sent,
        "test",
    )


def test_result_ready_requires_both_read_only_audits():
    result = IbkrUsMarketReadonlyAuditResult(etf_result(), overnight_result())
    assert result.ready is True
    assert IbkrUsMarketReadonlyAuditResult(
        etf_result(resolved=False), overnight_result()
    ).ready is False
    assert IbkrUsMarketReadonlyAuditResult(
        etf_result(), overnight_result(ready=False)
    ).ready is False
    assert IbkrUsMarketReadonlyAuditResult(
        etf_result(sent=True), overnight_result()
    ).ready is False


def test_combined_audit_calls_both_without_orders(monkeypatch):
    seen = []

    def fake_etf(symbol, *, config, timeout):
        seen.append(("etf", symbol, timeout))
        return etf_result()

    def fake_overnight(symbol, *, config, timeout):
        seen.append(("overnight", symbol, timeout))
        return overnight_result()

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_us_market_readonly_audit.audit_ibkr_paper_etf",
        fake_etf,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_us_market_readonly_audit.audit_ibkr_paper_overnight_contract",
        fake_overnight,
    )

    result = run_ibkr_us_market_readonly_audit("spy", timeout=3.0)
    assert result.ready is True
    assert result.etf.order_sent is False
    assert result.overnight.order_sent is False
    assert seen == [("etf", "spy", 3.0), ("overnight", "spy", 3.0)]
