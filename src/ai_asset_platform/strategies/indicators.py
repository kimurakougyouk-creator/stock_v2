import pandas as pd

def add_indicators(df, ma_short=5, ma_middle=25, ma_long=75):
    """テクニカル指標を追加する"""

    # 移動平均線
    df["MA5"] = df["Close"].rolling(ma_short).mean()
    df["MA25"] = df["Close"].rolling(ma_middle).mean()
    df["MA75"] = df["Close"].rolling(ma_long).mean()

    # RSI
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()

    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()

    df["MACD"] = ema12 - ema26
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    # ATR
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(14).mean()

    # 出来高20日平均
    df["VOL20"] = df["Volume"].rolling(20).mean()

    return df
