import pytest

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.ibkr_connection import (
    _ConnectionProbe,
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


def test_connection_probe_error_matches_installed_ibapi_signature():
    """ibapi(10.x)はerror()をreqId, errorTime, errorCode, errorString,
    advancedOrderRejectJsonの5引数で呼ぶ。旧4引数シグネチャのままだと、
    接続直後の情報メッセージでTypeErrorになりnextValidIdを取得できない。
    """
    probe = _ConnectionProbe()

    probe.error(-1, 0, 2104, "Market data farm connection is OK", "")
    assert probe.ready.is_set() is False

    probe.error(-1, 0, 1100, "Connectivity between IB and TWS has been lost.", "")
    assert probe.ready.is_set() is True
