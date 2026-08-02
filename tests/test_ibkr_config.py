import pytest

from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
    create_ibkr_paper_config,
)


def test_tws_paper_config_is_safe():
    config = create_ibkr_paper_config()

    assert config.host == "127.0.0.1"
    assert config.port == 7497
    assert config.client_id == 0
    assert config.paper_trading is True
    assert config.allow_live_trading is False

    config.validate()


def test_gateway_paper_uses_safe_port():
    config = create_ibkr_paper_config(
        use_gateway=True,
    )

    assert config.port == 4002
    assert config.paper_trading is True
    assert config.allow_live_trading is False

    config.validate()


def test_live_connection_is_locked_by_default():
    config = IbkrConnectionConfig(
        port=7496,
        paper_trading=False,
        allow_live_trading=False,
    )

    with pytest.raises(
        RuntimeError,
        match="Live Tradingは安全ロック",
    ):
        config.validate()


def test_invalid_port_is_rejected():
    config = IbkrConnectionConfig(
        port=0,
    )

    with pytest.raises(
        ValueError,
        match="port",
    ):
        config.validate()


def test_negative_client_id_is_rejected():
    config = IbkrConnectionConfig(
        client_id=-1,
    )

    with pytest.raises(
        ValueError,
        match="client_id",
    ):
        config.validate()
