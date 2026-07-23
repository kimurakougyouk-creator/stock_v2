from datetime import datetime
from backtest import run_backtest
from optimizer import find_best_setting


class FakeSeries:
    def __init__(self, values):
        self.values = values
        self.iloc = self

    def __getitem__(self, index):
        return self.values[index]


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows
        self.index = [row["date"] for row in rows]

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, key):
        return FakeSeries([row[key] for row in self.rows])

    def copy(self):
        return FakeFrame([row.copy() for row in self.rows])


def test_total_profit_uses_final_capital_with_costs():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 1.0, "Buy": True},
        {"date": datetime(2024, 1, 2), "Close": 110.0, "ATR": 1.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=1_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        max_loss_pct=1.0,
        lot_size=1,
    )

    assert result["final_capital"] == 1_100_000
    assert result["total_profit"] == 10.0
    assert result["asset_curve"][0]["capital"] == 1_000_000
    assert result["asset_curve"][-1]["capital"] == result["final_capital"]
    assert len(result["asset_curve"]) == 2
    assert result["trades"][0]["shares"] == 10_000


def test_daily_asset_curve_tracks_unrealized_drawdown():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 50.0, "Buy": True},
        {"date": datetime(2024, 1, 2), "Close": 80.0, "ATR": 50.0, "Buy": False},
        {"date": datetime(2024, 1, 3), "Close": 120.0, "ATR": 50.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=1_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        take_profit_pct=0.50,
        stop_loss_pct=0.50,
        max_loss_pct=1.0,
        lot_size=1,
    )

    assert [point["capital"] for point in result["asset_curve"]] == [1_000_000, 800_000, 1_200_000]
    assert result["max_drawdown"] == 20.0


def test_nan_buy_signal_does_not_open_position():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 1.0, "Buy": float("nan")},
        {"date": datetime(2024, 1, 2), "Close": 110.0, "ATR": 1.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=1_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
    )

    assert result["trade_count"] == 0
    assert result["final_capital"] == 1_000_000


def test_backtest_exits_with_take_profit():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 50.0, "Buy": True},
        {"date": datetime(2024, 1, 2), "Close": 111.0, "ATR": 50.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=1_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        take_profit_pct=0.10,
        stop_loss_pct=0.50,
    )

    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "take_profit"


def test_backtest_exits_with_stop_loss():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 50.0, "Buy": True},
        {"date": datetime(2024, 1, 2), "Close": 94.0, "ATR": 50.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=1_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        take_profit_pct=0.50,
        stop_loss_pct=0.05,
    )

    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "stop_loss"


def test_backtest_exits_with_trailing_stop():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 5.0, "Buy": True},
        {"date": datetime(2024, 1, 2), "Close": 120.0, "ATR": 5.0, "Buy": False},
        {"date": datetime(2024, 1, 3), "Close": 106.0, "ATR": 5.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=1_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        take_profit_pct=0.50,
        stop_loss_pct=0.05,
    )

    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "trailing_stop"


def test_position_size_uses_risk_and_lot_size():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 50.0, "Buy": True},
        {"date": datetime(2024, 1, 2), "Close": 101.0, "ATR": 50.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=1_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        take_profit_pct=0.50,
        stop_loss_pct=0.05,
        max_loss_pct=0.01,
        lot_size=100,
    )

    trade = result["trades"][0]
    assert trade["shares"] == 2000
    assert trade["risk_amount"] == 10_000
    assert trade["capital_usage"] == 20.0


def test_position_size_does_not_exceed_available_capital():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 50.0, "Buy": True},
        {"date": datetime(2024, 1, 2), "Close": 101.0, "ATR": 50.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=100_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        take_profit_pct=0.50,
        stop_loss_pct=0.05,
        max_loss_pct=1.0,
        lot_size=100,
    )

    trade = result["trades"][0]
    assert trade["shares"] == 1000
    assert trade["capital_usage"] == 100.0


def test_position_size_skips_entry_below_minimum_lot():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 50.0, "Buy": True},
        {"date": datetime(2024, 1, 2), "Close": 101.0, "ATR": 50.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=10_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        take_profit_pct=0.50,
        stop_loss_pct=0.05,
        max_loss_pct=0.01,
        lot_size=100,
    )

    assert result["trade_count"] == 0
    assert result["final_capital"] == 10_000


def test_optimizer_excludes_results_below_min_trades(monkeypatch):
    import optimizer

    results = iter([
        {"trade_count": 4, "total_profit": 100.0, "win_rate": 100.0, "net_profit_yen": 1_000_000, "final_capital": 2_000_000, "total_commission": 0, "average_hold_days": 1, "max_drawdown": 0},
        {"trade_count": 5, "total_profit": 1.0, "win_rate": 50.0, "net_profit_yen": 10_000, "final_capital": 1_010_000, "total_commission": 0, "average_hold_days": 1, "max_drawdown": 0},
    ])

    monkeypatch.setattr(optimizer, "ATR_LIST", [2.0])
    monkeypatch.setattr(optimizer, "MA_LIST", [(5, 25, 75), (5, 20, 60)])
    monkeypatch.setattr(optimizer, "RSI_LIST", [(50, 60)])
    monkeypatch.setattr(optimizer, "TAKE_PROFIT_LIST", [0.10])
    monkeypatch.setattr(optimizer, "STOP_LOSS_LIST", [0.05])
    monkeypatch.setattr(optimizer, "MIN_TRADES", 5)
    monkeypatch.setattr(optimizer, "add_indicators", lambda df, *args: df)
    monkeypatch.setattr(optimizer, "create_buy_signal", lambda df, *args: df)
    monkeypatch.setattr(optimizer, "run_backtest", lambda *args, **kwargs: next(results))

    best = find_best_setting(FakeFrame([{"date": datetime(2024, 1, 1)}]))

    assert best["result"]["trade_count"] == 5
    assert best["result"]["total_profit"] == 1.0
    assert best["take_profit"] == 0.10
    assert best["stop_loss"] == 0.05
    assert best["all_results"][0][-1] is False
    assert best["all_results"][1][-1] is True


def test_optimizer_searches_take_profit_and_stop_loss_combinations(monkeypatch):
    import optimizer

    calls = []
    profits = iter([1.0, 4.0, 2.0, 3.0])

    def fake_run_backtest(*args, **kwargs):
        calls.append(kwargs)
        profit = next(profits)
        return {
            "trade_count": 5,
            "total_profit": profit,
            "win_rate": 50.0,
            "net_profit_yen": profit * 10_000,
            "final_capital": 1_000_000 + profit * 10_000,
            "total_commission": 0,
            "average_hold_days": 1,
            "max_drawdown": 0,
        }

    monkeypatch.setattr(optimizer, "ATR_LIST", [2.0])
    monkeypatch.setattr(optimizer, "MA_LIST", [(5, 25, 75)])
    monkeypatch.setattr(optimizer, "RSI_LIST", [(50, 60)])
    monkeypatch.setattr(optimizer, "TAKE_PROFIT_LIST", [0.08, 0.10])
    monkeypatch.setattr(optimizer, "STOP_LOSS_LIST", [0.03, 0.05])
    monkeypatch.setattr(optimizer, "MIN_TRADES", 5)
    monkeypatch.setattr(optimizer, "add_indicators", lambda df, *args: df)
    monkeypatch.setattr(optimizer, "create_buy_signal", lambda df, *args: df)
    monkeypatch.setattr(optimizer, "run_backtest", fake_run_backtest)

    best = find_best_setting(FakeFrame([{"date": datetime(2024, 1, 1)}]))

    assert len(calls) == 4
    assert best["take_profit"] == 0.08
    assert best["stop_loss"] == 0.05
    assert best["result"]["total_profit"] == 4.0
    assert {call["take_profit_pct"] for call in calls} == {0.08, 0.10}
    assert {call["stop_loss_pct"] for call in calls} == {0.03, 0.05}
