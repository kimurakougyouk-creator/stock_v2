from types import SimpleNamespace

from ai_asset_platform.brokers import ibkr_crypto_readonly_audit as audit


def test_crypto_readonly_audit_never_promotes_permission_or_sends_order(monkeypatch):
    def fake_discover(*, symbol, exchange, currency):
        assert symbol == "BTC"
        assert currency == "USD"
        return SimpleNamespace(
            connected=True,
            resolved=(exchange == "PAXOS"),
            endpoint_port=4002,
            candidates=(object(),) if exchange == "PAXOS" else (),
            errors=(),
        )

    monkeypatch.setattr(audit, "discover_ibkr_paper_crypto", fake_discover)
    result = audit.run_crypto_readonly_audit()

    assert result.api_catalog_visible is True
    assert result.account_permission_proven is False
    assert result.paper_trading_proven is False
    assert result.real_order_sent is False
    assert result.live_order_sent is False
    assert {row.exchange for row in result.venues} == {"PAXOS", "ZEROHASH"}


def test_crypto_readonly_audit_treats_no_candidates_as_evidence_not_permission(monkeypatch):
    monkeypatch.setattr(
        audit,
        "discover_ibkr_paper_crypto",
        lambda **kwargs: SimpleNamespace(
            connected=True,
            resolved=False,
            endpoint_port=4002,
            candidates=(),
            errors=("200: no security definition",),
        ),
    )
    result = audit.run_crypto_readonly_audit()

    assert result.api_catalog_visible is False
    assert result.account_permission_proven is False
    assert result.paper_trading_proven is False
    assert result.real_order_sent is False
    assert result.live_order_sent is False
