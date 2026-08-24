"""CLI for explicit stale legacy IBKR Paper fill retirement."""
from __future__ import annotations

import os

from ai_asset_platform.brokers.ibkr_legacy_fill_retirement import (
    LegacyFillRetirementError,
    retire_stale_legacy_ibkr_fills,
)


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    if not _enabled("AI_ASSET_ALLOW_STALE_LEGACY_RETIREMENT"):
        print("BLOCKED: explicit stale legacy retirement approval is missing.")
        print("No local ledger file was changed and no broker order was sent.")
        return 2

    try:
        result = retire_stale_legacy_ibkr_fills()
    except LegacyFillRetirementError as exc:
        print("===== IBKR STALE LEGACY FILL RETIREMENT =====")
        print("CHANGED       : False")
        print("REASON        :", str(exc))
        print("ORDER SENT    : False")
        return 1

    print("===== IBKR STALE LEGACY FILL RETIREMENT =====")
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
