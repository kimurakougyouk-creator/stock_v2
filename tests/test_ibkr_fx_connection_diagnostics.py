from ai_asset_platform.brokers.ibkr_fx_connection_diagnostics import (
    FxPaperConnectionDiagnostics,
)


def test_fx_connection_diagnostics_never_implies_order_transmission():
    result = FxPaperConnectionDiagnostics(
        host="127.0.0.1",
        gateway_port=4002,
        tws_port=7497,
        gateway_open=False,
        tws_open=False,
        errors=("closed",),
    )
    assert result.any_paper_endpoint_open is False


def test_fx_connection_diagnostics_accepts_either_paper_endpoint():
    gateway = FxPaperConnectionDiagnostics(
        host="127.0.0.1",
        gateway_port=4002,
        tws_port=7497,
        gateway_open=True,
        tws_open=False,
    )
    tws = FxPaperConnectionDiagnostics(
        host="127.0.0.1",
        gateway_port=4002,
        tws_port=7497,
        gateway_open=False,
        tws_open=True,
    )
    assert gateway.any_paper_endpoint_open is True
    assert tws.any_paper_endpoint_open is True
