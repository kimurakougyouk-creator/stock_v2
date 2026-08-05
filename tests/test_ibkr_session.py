import pytest

from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
)
from ai_asset_platform.brokers.ibkr_session import (
    open_ibkr_paper_session,
)


def test_session_rejects_non_paper_config():
    config = IbkrConnectionConfig(
        port=7496,
        paper_trading=False,
        allow_live_trading=True,
    )

    with pytest.raises(
        RuntimeError,
        match="Paper Trading設定ではない",
    ):
        open_ibkr_paper_session(config)


def test_session_rejects_live_permission():
    config = IbkrConnectionConfig(
        paper_trading=True,
        allow_live_trading=True,
    )

    with pytest.raises(
        RuntimeError,
        match="Live Trading許可中",
    ):
        open_ibkr_paper_session(config)


def test_session_module_does_not_send_orders():
    from pathlib import Path

    text = Path(
        "src/ai_asset_platform/brokers/ibkr_session.py"
    ).read_text(encoding="utf-8")

    assert ".placeOrder(" not in text
    assert "transmit = True" not in text
