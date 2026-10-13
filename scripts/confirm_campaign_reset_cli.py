#!/usr/bin/env python3
"""Thin CLI around confirm_campaign_reset.

This exists so an operator can advance the Live pilot campaign to a new
generation from a single, explicit, auditable command -- never implicitly,
never as part of any existing Pilot entrypoint, and never without typing the
exact dedicated confirmation value and a human-readable reason.

See confirm_campaign_reset's own docstring (live_pilot_send_journal.py) for
the full safety contract. In short: this is for exactly one situation -- the
sole send attempt permitted in the current campaign generation ended in a
state that can never reach a reconciled Phase 4 terminal outcome. It does
not touch the prior generation's journal, attempt marker, UNKNOWN state, or
rejection evidence; it does not authorize any new order; the one-shot
authorization and final send confirmation for any future pilot remain fully,
separately required exactly as before.

This script does not connect to a broker and cannot place, cancel, modify,
retry, flatten, or close an order.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_asset_platform.execution.live_pilot_send_journal import (
    confirm_campaign_reset,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--journal-dir", type=Path)
    args = parser.parse_args(argv)

    kwargs = dict(confirmation=args.confirmation, reason=args.reason)
    if args.journal_dir is not None:
        kwargs["directory"] = args.journal_dir

    try:
        record = confirm_campaign_reset(**kwargs)
    except (PermissionError, ValueError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
