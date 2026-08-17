import json

from dashboard import build_dashboard_html


def test_dashboard_shows_performance_health_score(tmp_path) -> None:
    trade_data = {
        "realized_trade_pnls": [
            1000.0,
            1000.0,
            1000.0,
            -500.0,
            1000.0,
            1000.0,
            -500.0,
            1000.0,
            1000.0,
            1000.0,
            -500.0,
            1000.0,
            1000.0,
            -500.0,
            1000.0,
            1000.0,
            1000.0,
            -500.0,
            1000.0,
            1000.0,
        ]
    }

    (tmp_path / "paper_trade_pnls.json").write_text(
        json.dumps(trade_data),
        encoding="utf-8",
    )

    dashboard_html = build_dashboard_html(tmp_path)

    assert "運用成績の健全度" in dashboard_html
    assert "総合スコア" in dashboard_html
    assert "100 / 100" in dashboard_html
    assert "<strong>評価</strong><br>A" in dashboard_html
    assert "<strong>状態</strong><br>優秀" in dashboard_html
    assert "取引数評価" in dashboard_html
    assert "勝率評価" in dashboard_html
    assert "利益効率評価" in dashboard_html
    assert "損益・リスク評価" in dashboard_html


def test_dashboard_shows_no_data_health_status(tmp_path) -> None:
    dashboard_html = build_dashboard_html(tmp_path)

    assert "0 / 100" in dashboard_html
    assert "<strong>評価</strong><br>N/A" in dashboard_html
    assert "<strong>状態</strong><br>データ不足" in dashboard_html
