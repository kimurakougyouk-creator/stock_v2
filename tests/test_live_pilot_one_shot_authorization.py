from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import ai_asset_platform.execution.live_pilot_one_shot_authorization as subject
from ai_asset_platform.execution.live_pilot_one_shot_authorization import (
    OPERATOR_CONFIRMATION_VALUE,
    authorization_consumed,
    consume_live_pilot_authorization,
    issue_live_pilot_authorization,
)


NOW = datetime(2026, 9, 6, 7, 0, 0, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64


def _issue(tmp_path: Path, **overrides):
    params = {
        "confirmation": OPERATOR_CONFIRMATION_VALUE,
        "intent_id": "live-pilot:AAPL:BUY:1:20260907",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "limit_price": 250.0,
        "estimated_notional_jpy": 37_500.0,
        "account_fingerprint": FINGERPRINT,
        "endpoint_port": 4001,
        "authorization_dir": tmp_path,
        "now": NOW,
    }
    params.update(overrides)
    return issue_live_pilot_authorization(**params)


def _consume(tmp_path: Path, nonce: str, **overrides):
    params = {
        "nonce": nonce,
        "intent_id": "live-pilot:AAPL:BUY:1:20260907",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "limit_price": 250.0,
        "estimated_notional_jpy": 37_500.0,
        "account_fingerprint": FINGERPRINT,
        "endpoint_port": 4001,
        "authorization_dir": tmp_path,
        "now": NOW + timedelta(seconds=1),
    }
    params.update(overrides)
    return consume_live_pilot_authorization(**params)


def test_missing_exact_operator_confirmation_cannot_issue(tmp_path: Path):
    with pytest.raises(PermissionError, match="operator confirmation"):
        _issue(tmp_path, confirmation="yes")
    assert list(tmp_path.iterdir()) == []


def test_authorization_binds_exact_pilot_and_is_single_use(tmp_path: Path):
    authorization = _issue(tmp_path)

    assert authorization.status == "AUTHORIZED_ONCE"
    assert authorization.raw_account_id_persisted is False
    assert authorization.broker_connection_used is False
    assert authorization.order_sent is False
    assert authorization.live_order_sent is False
    assert authorization_consumed(authorization.nonce, authorization_dir=tmp_path) is False

    consumed = _consume(tmp_path, authorization.nonce)
    assert consumed["status"] == "CONSUMED"
    assert authorization_consumed(authorization.nonce, authorization_dir=tmp_path) is True

    with pytest.raises(PermissionError, match="already been consumed"):
        _consume(tmp_path, authorization.nonce)


def test_mismatched_limit_price_fails_without_consuming(tmp_path: Path):
    authorization = _issue(tmp_path)

    with pytest.raises(PermissionError, match="limit_price"):
        _consume(tmp_path, authorization.nonce, limit_price=249.0)

    assert authorization_consumed(authorization.nonce, authorization_dir=tmp_path) is False


def test_wrong_account_or_endpoint_fails_closed(tmp_path: Path):
    authorization = _issue(tmp_path)

    with pytest.raises(PermissionError, match="account_fingerprint"):
        _consume(tmp_path, authorization.nonce, account_fingerprint="b" * 64)
    with pytest.raises(PermissionError, match="endpoint_port"):
        _consume(tmp_path, authorization.nonce, endpoint_port=7496)

    assert authorization_consumed(authorization.nonce, authorization_dir=tmp_path) is False


def test_expired_authorization_cannot_be_consumed(tmp_path: Path):
    authorization = _issue(tmp_path, ttl_seconds=10.0)

    with pytest.raises(PermissionError, match="expired"):
        _consume(
            tmp_path,
            authorization.nonce,
            now=NOW + timedelta(seconds=11),
        )

    assert authorization_consumed(authorization.nonce, authorization_dir=tmp_path) is False


def test_ttl_is_short_and_bounded(tmp_path: Path):
    with pytest.raises(ValueError, match="maximum"):
        _issue(tmp_path, ttl_seconds=301.0)


def test_invalid_live_endpoint_is_rejected_at_issue_time(tmp_path: Path):
    with pytest.raises(ValueError, match="audited Live endpoint"):
        _issue(tmp_path, endpoint_port=4002)


def test_consumption_fsyncs_directory_entries(tmp_path: Path, monkeypatch):
    """Codex P1: the consumed marker's directory entry (and the removal of the

    authorization file's entry) must be fsynced so a power loss right after
    consumption cannot silently permit consuming it again.
    """
    calls = []
    original = subject._fsync_parent_dir

    def spy(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(subject, "_fsync_parent_dir", spy)
    authorization = _issue(tmp_path)
    calls.clear()
    _consume(tmp_path, authorization.nonce)
    assert len(calls) >= 2
    assert all(call.parent == tmp_path for call in calls)


def test_module_contains_no_broker_order_transport():
    source = Path(
        "src/ai_asset_platform/execution/live_pilot_one_shot_authorization.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "reqOpenOrders(",
        "reqAllOpenOrders(",
        "enable_live_trading = True",
        "whatIf=True",
    )
    for token in forbidden:
        assert token not in source
