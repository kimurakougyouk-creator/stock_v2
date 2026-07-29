from ai_asset_platform.reports import calculate_performance


def test_calculate_advanced_performance_statistics():
    result = calculate_performance(
        [
            1000.0,
            500.0,
            -300.0,
            -200.0,
            -100.0,
            400.0,
            0.0,
            200.0,
            300.0,
        ]
    )

    assert result.profit_factor == 4.0
    assert result.maximum_winning_streak == 2
    assert result.maximum_losing_streak == 3


def test_profit_factor_is_infinite_without_losses():
    result = calculate_performance(
        [
            100.0,
            200.0,
        ]
    )

    assert result.profit_factor == float("inf")
    assert result.maximum_winning_streak == 2
    assert result.maximum_losing_streak == 0


def test_advanced_statistics_are_zero_without_trades():
    result = calculate_performance([])

    assert result.profit_factor == 0.0
    assert result.maximum_winning_streak == 0
    assert result.maximum_losing_streak == 0


def test_break_even_trade_resets_streaks():
    result = calculate_performance(
        [
            100.0,
            100.0,
            0.0,
            100.0,
            -50.0,
            -50.0,
        ]
    )

    assert result.maximum_winning_streak == 2
    assert result.maximum_losing_streak == 2
