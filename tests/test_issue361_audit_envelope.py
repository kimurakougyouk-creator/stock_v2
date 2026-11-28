"""Security regression tests for the inert audit-message envelope."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from issue361_audit_envelope import InvalidEnvelope, parse_audit_envelope


BASE = {
    "protocol": "STOCK_V2_AUDIT_V1",
    "kind": "AUDIT_REQUEST",
    "run_id": "bridge_20261024_audit1",
    "payload": "REQUEST_READONLY_PR_AUDIT",
    "in_reply_to_comment_id": None,
}


def test_request_valid():
    result = parse_audit_envelope(json.dumps(BASE))
    assert result.kind == "AUDIT_REQUEST"
    assert result.in_reply_to_comment_id is None


def test_result_valid():
    data = {**BASE, "kind": "AUDIT_RESULT", "payload": "AUDIT_INCONCLUSIVE",
            "in_reply_to_comment_id": 12345}
    assert parse_audit_envelope(json.dumps(data)).in_reply_to_comment_id == 12345


@pytest.mark.parametrize("changes", [
    {"protocol": "AI_BRIDGE_TEST_V1"},
    {"payload": "placeOrder"},
    {"kind": "RUN_COMMAND"},
    {"in_reply_to_comment_id": 1},
    {"run_id": "../unsafe"},
    {"run_id": ""},
    {"payload": "AUDIT_PASS"},
    {"extra_field": True},
])
def test_invalid_request(changes):
    with pytest.raises(InvalidEnvelope):
        parse_audit_envelope(json.dumps({**BASE, **changes}))


@pytest.mark.parametrize("reply_id", [True, "42", 0, -1, None, 0.5])
def test_invalid_result_reply_id(reply_id):
    data = {**BASE, "kind": "AUDIT_RESULT", "payload": "AUDIT_PASS",
            "in_reply_to_comment_id": reply_id}
    with pytest.raises(InvalidEnvelope):
        parse_audit_envelope(json.dumps(data))


def test_duplicate_field_rejected():
    text = json.dumps(BASE).replace('"kind": "AUDIT_REQUEST"', '"kind": "AUDIT_REQUEST", "kind": "AUDIT_RESULT"')
    with pytest.raises(InvalidEnvelope):
        parse_audit_envelope(text)


@pytest.mark.parametrize("message", ["[]", "null", '"x"', "{", " " * 3000])
def test_malformed_rejected(message):
    with pytest.raises(InvalidEnvelope):
        parse_audit_envelope(message)
