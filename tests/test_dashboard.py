from pathlib import Path

from dashboard import build_dashboard_html, write_dashboard_html


def test_build_dashboard_shows_performance_card(tmp_path: Path) -> None:
    html = build_dashboard_html(tmp_path)

    assert "Paper Trading運用成績" in html
    assert "総取引数" in html
    assert "勝率" in html
    assert "純損益" in html


def test_write_dashboard_html(tmp_path: Path) -> None:
    output = write_dashboard_html(tmp_path)

    assert output.exists()
    assert output.name == "dashboard.html"


def test_build_dashboard_shows_decision_log_summary(
    tmp_path: Path,
) -> None:
    report = tmp_path / "decision_log_report.csv"
    report.write_text(
        """Category,Item,Value
Summary,TotalDecisions,10
Summary,OrderedCount,3
Summary,NotOrderedCount,7
Summary,OrderRatePercent,30.0
Summary,AverageAIConfidence,82.5
Reason,AI最終判定,8
Reason,Time Stop,2
NotOrderedReason,リスク管理,7
""",
        encoding="utf-8-sig",
    )

    html = build_dashboard_html(tmp_path)

    assert "注文判断ログ集計" in html
    assert "判断件数" in html
    assert "10" in html
    assert "注文実行件数" in html
    assert "3" in html
    assert "注文未実行件数" in html
    assert "7" in html
    assert "30.0%" in html
    assert "82.5" in html
    assert "判断理由別集計" in html
    assert "AI最終判定: 8件" in html
    assert "Time Stop: 2件" in html
    assert "注文見送り理由" in html
    assert "リスク管理: 7件" in html

