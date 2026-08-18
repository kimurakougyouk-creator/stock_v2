import pytest

from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
)
from ai_asset_platform.brokers.ibkr_session import (
    _IbkrPaperClient,
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


def test_managed_accounts_callback_captures_account_list():
    client = _IbkrPaperClient()
    assert client.accounts == []

    client.managedAccounts("DUR570982")
    assert client.accounts == ["DUR570982"]


def test_managed_accounts_callback_splits_multiple_accounts():
    client = _IbkrPaperClient()

    client.managedAccounts("DUR570982,DUR999999,")
    assert client.accounts == ["DUR570982", "DUR999999"]


def test_session_module_does_not_send_orders():
    from pathlib import Path

    text = Path(
        "src/ai_asset_platform/brokers/ibkr_session.py"
    ).read_text(encoding="utf-8")

    assert ".placeOrder(" not in text
    assert "transmit = True" not in text
