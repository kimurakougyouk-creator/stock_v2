from risk_manager import calculate_position_size


def test_calculates_position_size_from_permitted_loss():
    result = calculate_position_size(
        trading_capital=1_000_000,
        risk_per_trade_rate=0.01,
        entry_price=1_000,
        stop_loss_rate=0.03,
        lot_size=100,
    )

    assert result == 300


def test_rounds_down_to_lot_size():
    result = calculate_position_size(
        trading_capital=1_000_000,
        risk_per_trade_rate=0.01,
        entry_price=800,
        stop_loss_rate=0.03,
        lot_size=100,
    )

    assert result == 400


def test_returns_zero_when_less_than_one_lot():
    result = calculate_position_size(
        trading_capital=100_000,
        risk_per_trade_rate=0.01,
        entry_price=5_000,
        stop_loss_rate=0.03,
        lot_size=100,
    )

    assert result == 0


def test_supports_single_share_market():
    result = calculate_position_size(
        trading_capital=10_000,
        risk_per_trade_rate=0.01,
        entry_price=100,
        stop_loss_rate=0.05,
        lot_size=1,
    )

    assert result == 20


def test_returns_zero_for_invalid_capital():
    assert calculate_position_size(
        trading_capital=0,
        risk_per_trade_rate=0.01,
        entry_price=1_000,
        stop_loss_rate=0.03,
    ) == 0


def test_returns_zero_for_invalid_risk_rate():
    assert calculate_position_size(
        trading_capital=1_000_000,
        risk_per_trade_rate=0,
        entry_price=1_000,
        stop_loss_rate=0.03,
    ) == 0


def test_returns_zero_for_invalid_entry_price():
    assert calculate_position_size(
        trading_capital=1_000_000,
        risk_per_trade_rate=0.01,
        entry_price=0,
        stop_loss_rate=0.03,
    ) == 0


def test_returns_zero_for_invalid_stop_loss_rate():
    assert calculate_position_size(
        trading_capital=1_000_000,
        risk_per_trade_rate=0.01,
        entry_price=1_000,
        stop_loss_rate=0,
    ) == 0


def test_returns_zero_for_non_numeric_value():
    assert calculate_position_size(
        trading_capital="invalid",
        risk_per_trade_rate=0.01,
        entry_price=1_000,
        stop_loss_rate=0.03,
    ) == 0
