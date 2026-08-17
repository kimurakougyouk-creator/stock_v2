import pytest

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.ibkr_connection import (
    probe_ibkr_paper_connection,
)


def test_connection_probe_rejects_non_paper_config():
    config = IbkrConnectionConfig(
        port=7496,
        paper_trading=False,
        allow_live_trading=True,
    )

    with pytest.raises(RuntimeError, match="Paper Trading設定ではない"):
        probe_ibkr_paper_connection(config)


def test_connection_probe_rejects_live_permission():
    config = IbkrConnectionConfig(
        paper_trading=True,
        allow_live_trading=True,
    )

    with pytest.raises(RuntimeError, match="Live Trading許可中"):
        probe_ibkr_paper_connection(config)
