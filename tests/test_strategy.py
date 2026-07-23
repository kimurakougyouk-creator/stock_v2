import pandas as pd

from strategy import create_buy_signal


def _base_signal_frame(ma25_values):
    return pd.DataFrame({
        "Close": [120.0, 121.0],
        "MA5": [110.0, 111.0],
        "MA25": ma25_values,
        "MA75": [90.0, 90.0],
        "RSI": [60.0, 60.0],
        "MACD": [2.0, 2.0],
        "Signal": [1.0, 1.0],
        "Volume": [2000, 2000],
        "VOL20": [1000, 1000],
    })


def test_buy_signal_requires_rising_middle_moving_average():
    rising = create_buy_signal(_base_signal_frame([100.0, 101.0]))
    falling = create_buy_signal(_base_signal_frame([101.0, 100.0]))

    assert rising["Buy"].iloc[1]
    assert not falling["Buy"].iloc[1]
