from ai_asset_platform.reports import calculate_performance


def test_calculate_maximum_drawdown():
    result = calculate_performance(
        [
            1000.0,
            500.0,
            -300.0,
            -200.0,
            -100.0,
            400.0,
        ]
    )

    assert result.maximum_drawdown == 600.0


def test_drawdown_can_start_with_a_loss():
    result = calculate_performance(
        [
            -300.0,
            100.0,
            -200.0,
        ]
    )

    assert result.maximum_drawdown == 400.0


def test_maximum_drawdown_is_zero_for_only_profits():
    result = calculate_performance(
        [
            100.0,
            200.0,
            300.0,
        ]
    )

    assert result.maximum_drawdown == 0.0


def test_maximum_drawdown_is_zero_without_trades():
    result = calculate_performance([])

    assert result.maximum_drawdown == 0.0
