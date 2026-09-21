import json

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


def test_audit_joins_durable_commission_report_by_exec_id(tmp_path):
    order_log = tmp_path / "paper_orders.jsonl"
    commission_report = tmp_path / "commissions.json"
    order_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "created_at": "2026-09-01T10:00:00+09:00",
                        "mode": "IBKR_PAPER",
                        "ticker": "9432.T",
                        "side": "BUY",
                        "shares": 100,
                        "reference_price": 150.0,
                        "currency": "JPY",
                        "fx_to_account_rate": 1.0,
                        "status": "FILLED",
                        "order_intent_id": "signal-runner:9432.T:BUY:100:2026-09-01T10:00:00+09:00",
                        "broker_exec_ids": ["buy-1"],
                        "broker_exec_fills": [{"exec_id": "buy-1", "shares": 100}],
                    }
                ),
                json.dumps(
                    {
                        "created_at": "2026-09-02T10:00:00+09:00",
                        "mode": "IBKR_PAPER",
                        "ticker": "9432.T",
                        "side": "SELL",
                        "shares": 100,
                        "reference_price": 160.0,
                        "currency": "JPY",
                        "fx_to_account_rate": 1.0,
                        "status": "FILLED",
                        "order_intent_id": "signal-runner:9432.T:SELL:100:2026-09-02T10:00:00+09:00",
                        "broker_exec_ids": ["sell-1"],
                        "broker_exec_fills": [{"exec_id": "sell-1", "shares": 100}],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    commission_report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "paper_only": True,
                "order_sent": False,
                "live_order_sent": False,
                "commissions": [
                    {"exec_id": "buy-1", "commission": 5.0, "currency": "JPY"},
                    {"exec_id": "sell-1", "commission": 5.0, "currency": "JPY"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = audit_strategy_profitability_evidence(
        order_log_path=order_log,
        commission_report_path=commission_report,
        account_currency="JPY",
    )

    assert result.evidence_status == "NET_POSITIVE_AFTER_FEES"
    assert result.fees_accounted is True
    assert result.net_realized_pnl == 990.0
    assert result.net_profitability_proven is False
    assert result.live_ready is False


def test_malformed_commission_report_blocks_profitability_report(tmp_path):
    order_log = tmp_path / "paper_orders.jsonl"
    commission_report = tmp_path / "commissions.json"
    order_log.write_text("", encoding="utf-8")
    commission_report.write_text("{broken-json", encoding="utf-8")

    result = audit_strategy_profitability_evidence(
        order_log_path=order_log,
        commission_report_path=commission_report,
        account_currency="JPY",
    )

    assert result.evidence_status == "BLOCKED_INPUT_EVIDENCE"
    assert result.net_profitability_proven is False
    assert result.live_ready is False
