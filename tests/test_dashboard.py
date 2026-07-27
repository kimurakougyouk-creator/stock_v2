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
