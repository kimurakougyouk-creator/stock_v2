def create_buy_signal(df, rsi_low=50, rsi_high=70):
    """買いシグナルを作成"""

    df["Buy"] = (
        (df["Close"] > df["MA25"]) &
        (df["MA25"] > df["MA75"]) &
        (df["MA5"] > df["MA25"]) &
        (df["RSI"] >= rsi_low) &
        (df["RSI"] <= rsi_high) &
        (df["MACD"] > df["Signal"]) &
        (df["Volume"] > df["VOL20"])
    )

    return df
