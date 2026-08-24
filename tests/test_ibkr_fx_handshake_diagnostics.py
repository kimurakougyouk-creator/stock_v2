from pathlib import Path

from ai_asset_platform.brokers.ibkr_fx_handshake_diagnostics import (
    IbkrFxHandshakeDiagnosticResult,
)


def test_handshake_result_ready_requires_connection_next_id_and_no_errors():
    result = IbkrFxHandshakeDiagnosticResult(
        connected=True,
        next_valid_id_received=True,
        endpoint_port=4002,
        client_id=242,
        server_version=180,
    )
    assert result.ready is True


def test_handshake_result_fails_closed_on_errors_or_missing_handshake():
    assert IbkrFxHandshakeDiagnosticResult(
        connected=False,
        next_valid_id_received=False,
        endpoint_port=4002,
        client_id=242,
        server_version=None,
    ).ready is False
    assert IbkrFxHandshakeDiagnosticResult(
        connected=True,
        next_valid_id_received=True,
        endpoint_port=4002,
        client_id=242,
        server_version=180,
        errors=("502: failed",),
    ).ready is False


def test_handshake_module_contains_no_broker_request_or_order_path():
    text = Path(
        "src/ai_asset_platform/brokers/ibkr_fx_handshake_diagnostics.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "placeOrder(",
        "cancelOrder(",
        "reqContractDetails(",
        "reqMktData(",
        "reqAccountSummary(",
        "reqPositions(",
        "reqExecutions(",
        "reqOpenOrders(",
        "reqCompletedOrders(",
    )
    for token in forbidden:
        assert token not in text


def test_wrapper_does_not_enable_paper_or_live_order_transmission():
    text = Path("ibkr_fx_handshake_diagnostics_once.sh").read_text(encoding="utf-8")
    assert "AI_ASSET_ENABLE_IBKR_PAPER=1" not in text
    assert "AI_ASSET_ENABLE_LIVE_TRADING=1" not in text
    assert "AI_ASSET_LIVE_TRADING_UNLOCKED=1" not in text
    assert "ibkr_fx_whatif_once.sh" not in text
