import json
from dashboard import build_dashboard_html, write_dashboard_html


def test_dashboard_renders_total_asset_equity_and_drawdown(tmp_path):
    orders = [
        {"created_at":"t1","ticker":"AAPL","side":"BUY","shares":2,"reference_price":100.0,"order_intent_id":"a"},
        {"created_at":"t2","ticker":"AAPL","side":"SELL","shares":1,"reference_price":120.0,"order_intent_id":"b"},
    ]
    (tmp_path / "paper_orders.jsonl").write_text("".join(json.dumps(x) + "\n" for x in orders), encoding="utf-8")
    html = build_dashboard_html(tmp_path)
    assert "総資産（Equity）" in html
    assert "1,040円" in html
    assert "総資産ベース最大Drawdown" in html
    assert "Equity Curve" in html


def test_write_dashboard_persists_equity_history_idempotently(tmp_path):
    order = {"created_at":"t1","ticker":"AAPL","side":"BUY","shares":1,"reference_price":100.0,"order_intent_id":"a"}
    (tmp_path / "paper_orders.jsonl").write_text(json.dumps(order) + "\n", encoding="utf-8")
    write_dashboard_html(tmp_path)
    write_dashboard_html(tmp_path)
    rows = (tmp_path / "equity_history.csv").read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(rows) == 2
