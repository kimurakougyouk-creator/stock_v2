from ai_asset_platform.reports.equity_dashboard import build_equity_summary_html
from ai_asset_platform.reports.equity_history import EquityPoint, append_equity_history


def test_dashboard_equity_summary_uses_total_assets_and_drawdown(tmp_path):
    path = tmp_path / "equity_history.csv"
    for point in [
        EquityPoint("t1", "a", 0, 0, 1000),
        EquityPoint("t2", "b", 0, 0, 1200),
        EquityPoint("t3", "c", 0, 0, 900),
    ]:
        append_equity_history(path, point)

    result = build_equity_summary_html(path)
    assert "総資産 Equity Curve" in result
    assert "900円" in result
    assert "300円" in result
    assert "3" in result
