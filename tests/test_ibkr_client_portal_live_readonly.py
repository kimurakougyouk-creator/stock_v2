from __future__ import annotations

import json
from pathlib import Path

import ai_asset_platform.brokers.ibkr_client_portal_live_readonly as module


RAW_ACCOUNT = "U1234567"


def _live_responses(*, login_type: int = 1, is_paper: bool = False, orders=None):
    if orders is None:
        orders = []
    return {
        "/sso/validate": {
            "RESULT": True,
            "LOGIN_TYPE": login_type,
        },
        "/iserver/accounts": {
            "accounts": [RAW_ACCOUNT],
            "selectedAccount": RAW_ACCOUNT,
            "isPaper": is_paper,
        },
        "/portfolio/accounts": [
            {
                "accountId": RAW_ACCOUNT,
                "currency": "JPY",
            }
        ],
        f"/iserver/account/{RAW_ACCOUNT}/summary": {
            "netLiquidationValue": 150000.0,
            "availableFunds": 120000.0,
            "securitiesGVP": 0.0,
            "totalCashValue": 120000.0,
            "cashBalances": [
                {"currency": "JPY", "balance": 100000.0, "settledCash": 100000.0},
                {"currency": "USD", "balance": 1000.0, "settledCash": 1000.0},
                {
                    "currency": "Total (in JPY)",
                    "balance": 120000.0,
                    "settledCash": 120000.0,
                },
            ],
        },
        f"/portfolio2/{RAW_ACCOUNT}/positions": [
            {
                "acctId": RAW_ACCOUNT,
                "conid": 265598,
                "contractDesc": "AAPL",
                "assetClass": "STK",
                "currency": "USD",
                "position": 0,
                "avgCost": 0,
                "mktValue": 0,
            }
        ],
        "/iserver/account/orders": {"orders": orders, "snapshot": True},
        "/iserver/exchangerate": {"rate": 150.0},
    }


def _requester(responses):
    calls = []

    def request(path, *, params=None, timeout=10.0):
        calls.append((path, params, timeout))
        return responses[path]

    return request, calls


def test_missing_confirmation_blocks_before_any_request():
    def explode(*args, **kwargs):
        raise AssertionError("network must not be touched without exact confirmation")

    result = module.collect_client_portal_live_readonly_evidence(
        confirmation="",
        request_json=explode,
    )

    assert result.ready is False
    assert result.broker_connection_used is False
    assert result.order_sent is False
    assert result.cancel_sent is False
    assert result.live_order_sent is False
    assert result.account_report is None


def test_paper_session_is_rejected_before_account_evidence():
    request, calls = _requester(_live_responses(login_type=2, is_paper=True))

    result = module.collect_client_portal_live_readonly_evidence(
        confirmation="READ_LIVE_ACCOUNT_ONLY",
        request_json=request,
        sleep_fn=lambda _: None,
    )

    assert result.ready is False
    assert "verified Live SSO session" in result.blockers[0]
    assert [item[0] for item in calls] == ["/sso/validate"]


def test_verified_live_session_builds_read_only_reports_without_raw_account_id():
    request, calls = _requester(_live_responses())

    result = module.collect_client_portal_live_readonly_evidence(
        confirmation="READ_LIVE_ACCOUNT_ONLY",
        request_json=request,
        sleep_fn=lambda _: None,
    )

    assert result.ready is True
    assert result.order_sent is False
    assert result.cancel_sent is False
    assert result.live_order_sent is False

    account = result.account_report
    orders = result.open_orders_report
    fx = result.fx_report
    assert account is not None and orders is not None and fx is not None

    assert account["endpoint_port"] == 5000
    assert account["transport"] == "CLIENT_PORTAL_GATEWAY"
    assert account["session_live_verified"] is True
    assert account["base_currency"] == "JPY"
    assert account["settled_cash_by_currency"] == {
        "JPY": 100000.0,
        "USD": 1000.0,
    }
    assert len(account["account_fingerprint"]) == 64
    assert account["raw_account_id_persisted"] is False
    assert account["positions"] == [
        {
            "conid": 265598,
            "symbol": "AAPL",
            "asset_class": "STK",
            "currency": "USD",
            "position": 0.0,
            "avg_cost": 0.0,
            "market_value": 0.0,
        }
    ]

    assert orders["open_order_count"] == 0
    assert orders["orders"] == []
    assert orders["cancel_sent"] is False

    assert fx["rate"] == 150.0
    assert fx["source"] == "CLIENT_PORTAL_EXCHANGE_RATE"

    serialized = json.dumps(
        {
            "account": account,
            "orders": orders,
            "fx": fx,
        },
        sort_keys=True,
    )
    assert RAW_ACCOUNT not in serialized

    order_calls = [item for item in calls if item[0] == "/iserver/account/orders"]
    assert len(order_calls) == 2
    assert order_calls[0][1] == {"force": "true"}
    assert order_calls[1][1] is None


def test_filled_and_cancelled_rows_are_not_counted_as_open():
    rows = [
        {
            "orderId": 1,
            "acct": RAW_ACCOUNT,
            "ticker": "AAPL",
            "status": "Filled",
        },
        {
            "orderId": 2,
            "acct": RAW_ACCOUNT,
            "ticker": "AAPL",
            "status": "Cancelled",
        },
    ]
    request, _ = _requester(_live_responses(orders=rows))

    result = module.collect_client_portal_live_readonly_evidence(
        confirmation="READ_LIVE_ACCOUNT_ONLY",
        request_json=request,
        sleep_fn=lambda _: None,
    )

    assert result.ready is True
    assert result.open_orders_report["open_order_count"] == 0
    assert result.open_orders_report["orders"] == []


def test_pending_cancel_is_conservatively_counted_as_open():
    rows = [
        {
            "orderId": 9,
            "acct": RAW_ACCOUNT,
            "ticker": "AAPL",
            "description1": "AAPL",
            "secType": "STK",
            "cashCcy": "USD",
            "listingExchange": "NASDAQ",
            "side": "BUY",
            "totalSize": 1,
            "orderType": "Limit",
            "status": "PendingCancel",
        }
    ]
    request, _ = _requester(_live_responses(orders=rows))

    result = module.collect_client_portal_live_readonly_evidence(
        confirmation="READ_LIVE_ACCOUNT_ONLY",
        request_json=request,
        sleep_fn=lambda _: None,
    )

    assert result.ready is True
    report = result.open_orders_report
    assert report["open_order_count"] == 1
    assert report["orders"][0]["status"] == "PendingCancel"


def test_active_order_from_unverified_account_fails_closed_without_leaking_id():
    rows = [
        {
            "orderId": 10,
            "acct": "U9999999",
            "ticker": "AAPL",
            "status": "Submitted",
        }
    ]
    request, _ = _requester(_live_responses(orders=rows))

    result = module.collect_client_portal_live_readonly_evidence(
        confirmation="READ_LIVE_ACCOUNT_ONLY",
        request_json=request,
        sleep_fn=lambda _: None,
    )

    assert result.ready is False
    assert result.account_report is None
    assert "U9999999" not in " ".join(result.blockers)


def test_source_is_hard_limited_to_read_only_get_transport():
    source = Path(
        "src/ai_asset_platform/brokers/ibkr_client_portal_live_readonly.py"
    ).read_text(encoding="utf-8")

    assert 'method="GET"' in source
    forbidden = (
        'method="POST"',
        "/orders/whatif",
        "/iserver/reply/",
        "/iserver/account/order/",
        "/iserver/questions/suppress",
        "/iserver/auth/ssodh/init",
        "enable_live_trading = True",
        "live_trading_unlocked = True",
        ".placeOrder(",
        ".cancelOrder(",
    )
    for token in forbidden:
        assert token not in source
