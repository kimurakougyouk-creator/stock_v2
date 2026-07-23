from datetime import datetime
import sys
import types

sys.modules.setdefault("indicators", types.SimpleNamespace(add_indicators=lambda df, *args: df))
sys.modules.setdefault("strategy", types.SimpleNamespace(create_buy_signal=lambda df, *args: df))

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
    )

    assert result["final_capital"] == 1_100_000
    assert result["total_profit"] == 10.0
    assert result["asset_curve"][0]["capital"] == 1_000_000
    assert result["asset_curve"][-1]["capital"] == result["final_capital"]


def test_optimizer_excludes_results_below_min_trades(monkeypatch):
    import optimizer

    results = iter([
        {"trade_count": 4, "total_profit": 100.0, "win_rate": 100.0, "net_profit_yen": 1_000_000, "final_capital": 2_000_000, "total_commission": 0, "average_hold_days": 1, "max_drawdown": 0},
        {"trade_count": 5, "total_profit": 1.0, "win_rate": 50.0, "net_profit_yen": 10_000, "final_capital": 1_010_000, "total_commission": 0, "average_hold_days": 1, "max_drawdown": 0},
    ])

    monkeypatch.setattr(optimizer, "ATR_LIST", [2.0])
    monkeypatch.setattr(optimizer, "MA_LIST", [(5, 25, 75), (5, 20, 60)])
    monkeypatch.setattr(optimizer, "RSI_LIST", [(50, 60)])
    monkeypatch.setattr(optimizer, "MIN_TRADES", 5)
    monkeypatch.setattr(optimizer, "add_indicators", lambda df, *args: df)
    monkeypatch.setattr(optimizer, "create_buy_signal", lambda df, *args: df)
    monkeypatch.setattr(optimizer, "run_backtest", lambda *args, **kwargs: next(results))

    best = find_best_setting(FakeFrame([{"date": datetime(2024, 1, 1)}]))

    assert best["result"]["trade_count"] == 5
    assert best["result"]["total_profit"] == 1.0
    assert best["all_results"][0][-1] is False
    assert best["all_results"][1][-1] is True
