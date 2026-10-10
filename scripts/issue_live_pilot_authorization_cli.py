#!/usr/bin/env python3
"""Thin CLI around issue_live_pilot_authorization, recovery-aware.

This exists so live_pilot_operational_once.ps1 (the Windows operational
wrapper) can obtain the exact nonce the operational entrypoint needs, in
one invocation, without the operator ever seeing or transcribing it.
live_pilot_operational_once.sh (POSIX) does not use this script and is
unchanged: that wrapper still requires an externally prepared
LIVE_PILOT_NONCE, per its own existing contract.

Codex P1 (PR #341 review): a prior revision of this CLI always issued a
fresh authorization, including on a recovery run (one made after a
global Live-pilot send attempt was already recorded). The entrypoint's
recovery/reconciliation path (_request_matches_durable_authorization)
requires the *consumed* nonce already durably recorded in that attempt's
send journal, not a new one -- a fresh nonce can never match, which
would have silently broken UNKNOWN/partial/rejected reconciliation after
any real attempt. This CLI now checks for that condition itself:
- If no global send attempt has ever been recorded: issue a fresh
  authorization as before and print its newly generated nonce.
- If a global send attempt already exists for this intent_id: do not
  issue anything new. Load that intent's existing send journal and print
  the nonce it already recorded, so recovery runs bind correctly.

On success, prints exactly the nonce to stdout (nothing else) so a
calling shell can capture it directly. On any failure, prints a message
to stderr and exits non-zero; nothing is printed to stdout in that case.

This script does not connect to a broker and cannot place, cancel,
modify, retry, flatten, or close an order -- see
live_pilot_one_shot_authorization.py's own module docstring.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_asset_platform.execution.live_pilot_one_shot_authorization import (
    issue_live_pilot_authorization,
)
from ai_asset_platform.execution.live_pilot_send_journal import (
    global_send_attempt_recorded,
    load_send_journal,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--intent-id", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--side", required=True)
    parser.add_argument("--quantity", required=True, type=int)
    parser.add_argument("--limit-price", required=True, type=float)
    parser.add_argument("--estimated-notional-jpy", required=True, type=float)
    parser.add_argument("--account-fingerprint", required=True)
    parser.add_argument("--endpoint-port", required=True, type=int)
    parser.add_argument("--authorization-dir", type=Path)
    parser.add_argument("--journal-dir", type=Path)
    args = parser.parse_args(argv)

    journal_kwargs = {}
    if args.journal_dir is not None:
        journal_kwargs["directory"] = args.journal_dir

    if global_send_attempt_recorded(**journal_kwargs):
        journal = load_send_journal(args.intent_id, **journal_kwargs)
        nonce = journal.get("nonce") if isinstance(journal, dict) else None
        if not nonce:
            print(
                "BLOCKED: a prior Live pilot send attempt was recorded, but "
                "no durable nonce could be loaded for this intent_id to "
                "recover with",
                file=sys.stderr,
            )
            return 2
        sys.stdout.write(str(nonce))
        return 0

    kwargs = dict(
        confirmation=args.confirmation,
        intent_id=args.intent_id,
        ticker=args.ticker,
        side=args.side,
        quantity=args.quantity,
        limit_price=args.limit_price,
        estimated_notional_jpy=args.estimated_notional_jpy,
        account_fingerprint=args.account_fingerprint,
        endpoint_port=args.endpoint_port,
    )
    if args.authorization_dir is not None:
        kwargs["authorization_dir"] = args.authorization_dir

    try:
        authorization = issue_live_pilot_authorization(**kwargs)
    except (PermissionError, ValueError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    sys.stdout.write(authorization.nonce)
    return 0


if __name__ == "__main__":
    sys.exit(main())
