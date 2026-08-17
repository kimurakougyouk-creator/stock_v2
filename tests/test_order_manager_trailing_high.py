from __future__ import annotations

import json

import order_manager


def _use_temporary_path(monkeypatch, tmp_path):
    trailing_path = tmp_path / "trailing_high_prices.json"

    monkeypatch.setattr(
        order_manager,
        "ORDER_LOG_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        order_manager,
        "TRAILING_HIGH_PATH",
        trailing_path,
    )

    return trailing_path


def test_load_returns_empty_when_file_does_not_exist(
    monkeypatch,
    tmp_path,
):
    _use_temporary_path(monkeypatch, tmp_path)

    assert order_manager.load_trailing_high_prices() == {}


def test_first_price_is_saved_as_high(
    monkeypatch,
    tmp_path,
):
    trailing_path = _use_temporary_path(
        monkeypatch,
        tmp_path,
    )

    highest = order_manager.update_trailing_high_price(
        "7203.T",
        2500.0,
        held_shares=100,
    )

    assert highest == 2500.0
    assert trailing_path.exists()
    assert order_manager.load_trailing_high_prices() == {
        "7203.T": 2500.0
    }


def test_higher_price_updates_high(
    monkeypatch,
    tmp_path,
):
    _use_temporary_path(monkeypatch, tmp_path)

    order_manager.update_trailing_high_price(
        "7203.T",
        2500.0,
        held_shares=100,
    )

    highest = order_manager.update_trailing_high_price(
        "7203.T",
        2700.0,
        held_shares=100,
    )

    assert highest == 2700.0
    assert order_manager.load_trailing_high_prices() == {
        "7203.T": 2700.0
    }


def test_lower_price_does_not_replace_high(
    monkeypatch,
    tmp_path,
):
    _use_temporary_path(monkeypatch, tmp_path)

    order_manager.update_trailing_high_price(
        "7203.T",
        2700.0,
        held_shares=100,
    )

    highest = order_manager.update_trailing_high_price(
        "7203.T",
        2600.0,
        held_shares=100,
    )

    assert highest == 2700.0
    assert order_manager.load_trailing_high_prices() == {
        "7203.T": 2700.0
    }


def test_zero_position_removes_saved_high(
    monkeypatch,
    tmp_path,
):
    _use_temporary_path(monkeypatch, tmp_path)

    order_manager.update_trailing_high_price(
        "7203.T",
        2700.0,
        held_shares=100,
    )

    highest = order_manager.update_trailing_high_price(
        "7203.T",
        2600.0,
        held_shares=0,
    )

    assert highest is None
    assert order_manager.load_trailing_high_prices() == {}


def test_invalid_saved_values_are_ignored(
    monkeypatch,
    tmp_path,
):
    trailing_path = _use_temporary_path(
        monkeypatch,
        tmp_path,
    )

    trailing_path.write_text(
        json.dumps(
            {
                "7203.T": 2500,
                "6758.T": "invalid",
                "9984.T": -100,
            }
        ),
        encoding="utf-8",
    )

    assert order_manager.load_trailing_high_prices() == {
        "7203.T": 2500.0
    }


def test_invalid_current_price_keeps_existing_high(
    monkeypatch,
    tmp_path,
):
    _use_temporary_path(monkeypatch, tmp_path)

    order_manager.update_trailing_high_price(
        "7203.T",
        2500.0,
        held_shares=100,
    )

    highest = order_manager.update_trailing_high_price(
        "7203.T",
        0,
        held_shares=100,
    )

    assert highest == 2500.0
