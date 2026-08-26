"""CLI for exact verified derivative cleanup from the legacy Paper ledger."""
from __future__ import annotations

import os

from ai_asset_platform.brokers.ibkr_verified_derivative_ledger_cleanup import (
    VerifiedDerivativeLedgerCleanupError,
    quarantine_verified_derivative_rows,
)


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    if not _enabled("AI_ASSET_ALLOW_VERIFIED_DERIVATIVE_LEDGER_CLEANUP"):
        print("BLOCKED: explicit verified derivative ledger cleanup approval is missing.")
        print("No local ledger file was changed and no broker order was sent.")
        return 2

    try:
        result = quarantine_verified_derivative_rows()
    except VerifiedDerivativeLedgerCleanupError as exc:
        print("===== VERIFIED DERIVATIVE LEDGER CLEANUP =====")
        print("CHANGED       : False")
        print("REASON        :", str(exc))
        print("ORDER SENT    : False")
        return 1

    print("===== VERIFIED DERIVATIVE LEDGER CLEANUP =====")
    print("CHANGED       :", result.changed)
    print("REASON        :", result.reason)
    print("RETIRED COUNT :", result.retired_count)
    print("RETIRED INTENTS:", list(result.retired_intent_ids))
    print("BACKUP        :", result.backup_path)
    print("QUARANTINE    :", result.quarantine_path)
    print("ORDER SENT    :", result.order_sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
