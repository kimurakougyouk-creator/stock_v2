"""Approval-gated CLI for exact closed-SPY durable FX repair."""
from __future__ import annotations

import os

from ai_asset_platform.brokers.ibkr_closed_spy_fx_ledger_repair import (
    ClosedSpyFxLedgerRepairError,
    repair_closed_spy_buy_fx,
)


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    if not _enabled("AI_ASSET_ALLOW_CLOSED_SPY_FX_LEDGER_REPAIR"):
        print("BLOCKED: explicit closed SPY FX ledger repair approval is missing.")
        print("No local ledger file was changed and no broker order was sent.")
        return 2

    try:
        result = repair_closed_spy_buy_fx()
    except ClosedSpyFxLedgerRepairError as exc:
        print("===== CLOSED SPY FX LEDGER REPAIR =====")
        print("CHANGED       : False")
        print("REASON        :", str(exc))
        print("ORDER SENT    : False")
        return 1

    print("===== CLOSED SPY FX LEDGER REPAIR =====")
    print("CHANGED       :", result.changed)
    print("REASON        :", result.reason)
    print("REPAIRED INTENT:", result.repaired_intent_id)
    print("FX RATE       :", result.fx_to_account_rate)
    print("REFERENCE EXEC IDS:", list(result.reference_exec_ids))
    print("BACKUP        :", result.backup_path)
    print("ORDER SENT    :", result.order_sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
