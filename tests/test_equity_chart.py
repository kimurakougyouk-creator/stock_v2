import csv
from ai_asset_platform.reports.equity_chart import build_equity_chart_html
from ai_asset_platform.reports.equity_history import EQUITY_HISTORY_FIELDS


def write_history(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=EQUITY_HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_chart_requires_two_valid_points(tmp_path):
    html = build_equity_chart_html(tmp_path / "missing.csv")
    assert "まだありません" in html


def test_chart_uses_total_assets_not_realized_pnl(tmp_path):
    path = tmp_path / "equity.csv"
    write_history(path, [
        {"recorded_at":"t1","cash":900,"holdings":100,"total_assets":1000,"realized_pnl":99999,"unrealized_pnl":0},
        {"recorded_at":"t2","cash":800,"holdings":250,"total_assets":1050,"realized_pnl":99999,"unrealized_pnl":50},
    ])
    html = build_equity_chart_html(path)
    assert "Equity Curve" in html
    assert "1,050円" in html
    assert "99,999" not in html


def test_chart_skips_malformed_rows(tmp_path):
    path = tmp_path / "equity.csv"
    write_history(path, [
        {"recorded_at":"bad","cash":0,"holdings":0,"total_assets":"bad","realized_pnl":0,"unrealized_pnl":0},
        {"recorded_at":"t1","cash":900,"holdings":100,"total_assets":1000,"realized_pnl":0,"unrealized_pnl":0},
        {"recorded_at":"t2","cash":800,"holdings":250,"total_assets":1050,"realized_pnl":0,"unrealized_pnl":50},
    ])
    assert "直近2件" in build_equity_chart_html(path)
