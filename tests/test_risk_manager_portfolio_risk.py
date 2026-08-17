from risk_manager import calculate_open_position_risk


def test_calculates_risk_for_single_open_position():
    orders = [
        {
            "ticker": "7203.T",
            "side": "BUY",
            "shares": 100,
            "reference_price": 1_000,
        }
    ]

    result = calculate_open_position_risk(
        orders,
        stop_loss_rate=0.03,
    )

    assert result == 3_000


def test_calculates_total_risk_for_multiple_positions():
    orders = [
        {
            "ticker": "7203.T",
            "side": "BUY",
            "shares": 100,
            "reference_price": 1_000,
        },
        {
            "ticker": "6758.T",
            "side": "BUY",
            "shares": 200,
            "reference_price": 500,
        },
    ]

    result = calculate_open_position_risk(
        orders,
        stop_loss_rate=0.03,
    )

    assert result == 6_000


def test_uses_average_cost_for_repeated_buys():
    orders = [
        {
            "ticker": "7203.T",
            "side": "BUY",
            "shares": 100,
            "reference_price": 1_000,
        },
        {
            "ticker": "7203.T",
            "side": "BUY",
            "shares": 100,
            "reference_price": 2_000,
        },
    ]

    result = calculate_open_position_risk(
        orders,
        stop_loss_rate=0.03,
    )

    assert result == 9_000


def test_reduces_risk_after_partial_sell():
    orders = [
        {
            "ticker": "7203.T",
            "side": "BUY",
            "shares": 200,
            "reference_price": 1_000,
        },
        {
            "ticker": "7203.T",
            "side": "SELL",
            "shares": 100,
            "reference_price": 1_200,
        },
    ]

    result = calculate_open_position_risk(
        orders,
        stop_loss_rate=0.03,
    )

    assert result == 3_000


def test_returns_zero_after_full_sell():
    orders = [
        {
            "ticker": "7203.T",
            "side": "BUY",
            "shares": 100,
            "reference_price": 1_000,
        },
        {
            "ticker": "7203.T",
            "side": "SELL",
            "shares": 100,
            "reference_price": 1_200,
        },
    ]

    result = calculate_open_position_risk(
        orders,
        stop_loss_rate=0.03,
    )

    assert result == 0


def test_ignores_invalid_orders():
    orders = [
        {},
        {
            "ticker": "7203.T",
            "side": "BUY",
            "shares": "invalid",
            "reference_price": 1_000,
        },
    ]

    result = calculate_open_position_risk(
        orders,
        stop_loss_rate=0.03,
    )

    assert result == 0


def test_returns_zero_for_invalid_stop_loss_rate():
    assert calculate_open_position_risk(
        [],
        stop_loss_rate=0,
    ) == 0
