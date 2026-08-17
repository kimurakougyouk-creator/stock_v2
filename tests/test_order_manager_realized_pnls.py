import json

import pytest

import order_manager


@pytest.fixture
def isolated_order_files(tmp_path, monkeypatch):
    """テスト用の注文・損益ファイルへ切り替える。"""
    order_log_path = tmp_path / "paper_orders.jsonl"
    trade_pnl_path = tmp_path / "paper_trade_pnls.json"

    monkeypatch.setattr(order_manager, "ORDER_LOG_DIR", tmp_path)
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", order_log_path)
    monkeypatch.setattr(order_manager, "TRADE_PNL_PATH", trade_pnl_path)

    return order_log_path, trade_pnl_path


def test_realized_trade_pnl_is_saved_after_sell(isolated_order_files):
    """BUY後のSELLで実現損益がJSONへ保存される。"""
    _, trade_pnl_path = isolated_order_files

    order_manager.create_paper_order(
        ticker="7203.T",
        signal="BUY",
        shares=10,
        reference_price=1000.0,
    )
    order_manager.create_paper_order(
        ticker="7203.T",
        signal="SELL",
        shares=10,
        reference_price=1100.0,
    )

    assert order_manager.calculate_realized_trade_pnls() == [1000.0]
    assert trade_pnl_path.exists()

    payload = json.loads(
        trade_pnl_path.read_text(encoding="utf-8")
    )

    assert "updated_at" in payload
    assert payload["realized_trade_pnls"] == [1000.0]


def test_realized_trade_pnl_uses_weighted_average_cost(
    isolated_order_files,
):
    """複数回BUYした場合は加重平均取得価格で損益計算する。"""
    _, trade_pnl_path = isolated_order_files

    order_manager.create_paper_order(
        ticker="6758.T",
        signal="BUY",
        shares=10,
        reference_price=1000.0,
    )
    order_manager.create_paper_order(
        ticker="6758.T",
        signal="BUY",
        shares=10,
        reference_price=1200.0,
    )
    order_manager.create_paper_order(
        ticker="6758.T",
        signal="SELL",
        shares=5,
        reference_price=1300.0,
    )

    assert order_manager.calculate_realized_trade_pnls() == [1000.0]

    payload = json.loads(
        trade_pnl_path.read_text(encoding="utf-8")
    )
    assert payload["realized_trade_pnls"] == [1000.0]


def test_sell_more_than_position_uses_held_shares_only(
    isolated_order_files,
):
    """保有株数を超えるSELLは保有分だけ損益計算する。"""
    _, trade_pnl_path = isolated_order_files

    order_manager.create_paper_order(
        ticker="9984.T",
        signal="BUY",
        shares=5,
        reference_price=2000.0,
    )
    order_manager.create_paper_order(
        ticker="9984.T",
        signal="SELL",
        shares=10,
        reference_price=2100.0,
    )

    assert order_manager.calculate_realized_trade_pnls() == [500.0]

    payload = json.loads(
        trade_pnl_path.read_text(encoding="utf-8")
    )
    assert payload["realized_trade_pnls"] == [500.0]


def test_realized_trade_details_are_saved(isolated_order_files):
    """銘柄・株数・価格・損益・売却日時がJSONへ保存される。"""
    _, trade_pnl_path = isolated_order_files

    order_manager.create_paper_order(
        ticker="7203.T",
        signal="BUY",
        shares=10,
        reference_price=1000.0,
    )
    order_manager.create_paper_order(
        ticker="7203.T",
        signal="SELL",
        shares=10,
        reference_price=1100.0,
    )

    payload = json.loads(
        trade_pnl_path.read_text(encoding="utf-8")
    )

    assert payload["realized_trades"] == [
        {
            "ticker": "7203.T",
            "shares": 10,
            "average_cost": 1000.0,
            "sell_price": 1100.0,
            "realized_pnl": 1000.0,
            "sold_at": payload["realized_trades"][0]["sold_at"],
        }
    ]
    assert payload["realized_trades"][0]["sold_at"]

