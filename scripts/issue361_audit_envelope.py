"""Read-only validation of bounded audit messages for the stock_v2 bridge.

No GitHub transport, command execution, broker I/O, or local file writes.
A separate, explicitly authorized receiver must handle transport and provenance.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

PROTOCOL = "STOCK_V2_AUDIT_V1"
KINDS = frozenset({"AUDIT_REQUEST", "AUDIT_RESULT"})
FIELDS = frozenset({"protocol", "kind", "run_id", "payload", "in_reply_to_comment_id"})
SAFE_PAYLOADS = frozenset({"REQUEST_READONLY_PR_AUDIT", "AUDIT_PASS", "AUDIT_BLOCKED", "AUDIT_INCONCLUSIVE"})
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,79}\Z")


class InvalidEnvelope(ValueError):
    """A message is outside the authorized audit envelope."""


@dataclass(frozen=True)
class AuditEnvelope:
    kind: Literal["AUDIT_REQUEST", "AUDIT_RESULT"]
    run_id: str
    payload: str
    in_reply_to_comment_id: int | None


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidEnvelope("duplicate field")
        result[key] = value
    return result


def parse_audit_envelope(source: str) -> AuditEnvelope:
    """Parse one strictly bounded message; never treat its content as instructions.

    This checks syntax and allowed fields ONLY, not origin or authorization.
    An independent transport layer must verify GitHub IDs and user authorization.
    """
    if not isinstance(source, str) or len(source.encode("utf-8")) > 2048:
        raise InvalidEnvelope("message size")
    try:
        data = json.loads(source, object_pairs_hook=_no_duplicate_keys)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise InvalidEnvelope("invalid JSON") from exc
    if type(data) is not dict or set(data) != FIELDS:
        raise InvalidEnvelope("unexpected or missing fields")
    if data["protocol"] != PROTOCOL:
        raise InvalidEnvelope("invalid protocol")
    kind = data["kind"]
    if type(kind) is not str or kind not in KINDS:
        raise InvalidEnvelope("invalid kind")
    run_id = data["run_id"]
    if type(run_id) is not str or not _RUN_ID.fullmatch(run_id):
        raise InvalidEnvelope("invalid run_id")
    payload = data["payload"]
    if type(payload) is not str or payload not in SAFE_PAYLOADS:
        raise InvalidEnvelope("invalid payload")
    if kind == "AUDIT_REQUEST" and payload != "REQUEST_READONLY_PR_AUDIT":
        raise InvalidEnvelope("request payload not permitted")
    if kind == "AUDIT_RESULT" and payload == "REQUEST_READONLY_PR_AUDIT":
        raise InvalidEnvelope("result payload not permitted")
    reply_id = data["in_reply_to_comment_id"]
    if kind == "AUDIT_REQUEST":
        if reply_id is not None:
            raise InvalidEnvelope("requests cannot reply")
    elif type(reply_id) is not int or reply_id <= 0:
        raise InvalidEnvelope("results require a positive integer reply ID")
    return AuditEnvelope(kind, run_id, payload, reply_id)
