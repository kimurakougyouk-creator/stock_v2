from datetime import datetime
import sys
import types

sys.modules.setdefault("indicators", types.SimpleNamespace(add_indicators=lambda df, *args: df))
sys.modules.setdefault("strategy", types.SimpleNamespace(create_buy_signal=lambda df, *args: df))

from backtest import run_backtest


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


def test_stop_loss_exit_reason():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 1.0, "Buy": True},
        {"date": datetime(2024, 1, 2), "Close": 96.0, "ATR": 1.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=1_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        stop_loss_rate=0.03,
        take_profit_rate=0.06,
    )

    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "stop_loss"
    assert result["trades"][0]["profit"] < 0


def test_take_profit_exit_reason():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 1.0, "Buy": True},
        {"date": datetime(2024, 1, 2), "Close": 106.0, "ATR": 1.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=1_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        stop_loss_rate=0.03,
        take_profit_rate=0.06,
    )

    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "take_profit"
    assert result["trades"][0]["profit"] > 0


def test_atr_stop_exit_reason():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 3.0, "Buy": True},
        {"date": datetime(2024, 1, 2), "Close": 105.0, "ATR": 3.0, "Buy": False},
        {"date": datetime(2024, 1, 3), "Close": 98.0, "ATR": 3.0, "Buy": False},
        {"date": datetime(2024, 1, 4), "Close": 97.4, "ATR": 3.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=1_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        stop_loss_rate=0.03,
        take_profit_rate=0.06,
    )

    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "atr_stop"


def test_final_close_exit_reason():
    df = FakeFrame([
        {"date": datetime(2024, 1, 1), "Close": 100.0, "ATR": 1.0, "Buy": True},
        {"date": datetime(2024, 1, 2), "Close": 101.0, "ATR": 1.0, "Buy": False},
    ])

    result = run_backtest(
        df,
        atr_multiplier=2.5,
        initial_capital=1_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        stop_loss_rate=0.03,
        take_profit_rate=0.06,
    )

    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "final_close"
