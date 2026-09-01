from ai_asset_platform.reports.strategy_profitability_evidence import (
    audit_strategy_profitability_evidence,
)


def test_malformed_order_log_blocks_profitability_report(tmp_path):
    order_log = tmp_path / "paper_orders.jsonl"
    order_log.write_text(
        '{"mode":"IBKR_PAPER","status":"FILLED"}\n{broken-json\n',
        encoding="utf-8",
    )

    result = audit_strategy_profitability_evidence(
        order_log_path=order_log,
        account_currency="JPY",
    )

    assert result.evidence_status == "BLOCKED_INPUT_EVIDENCE"
    assert result.gross_result == "UNKNOWN"
    assert result.net_profitability_proven is False
    assert result.live_ready is False
    assert "blocked" in result.reason.lower()
