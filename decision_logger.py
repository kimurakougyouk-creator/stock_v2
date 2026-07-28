from __future__ import annotations

from datetime import datetime
from pathlib import Path
import csv


LOG_FILE = Path("results") / "decision_log.csv"


def log_decision(
    *,
    ticker: str,
    final_signal: str,
    ordered: bool,
    reason: str,
    ai_signal: str,
    ai_confidence: float,
    technical_signal: str,
) -> None:
    """注文判断ログをCSVへ追記します。"""

    LOG_FILE.parent.mkdir(exist_ok=True)

    file_exists = LOG_FILE.exists()

    with LOG_FILE.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(
                [
                    "Timestamp",
                    "Ticker",
                    "FinalSignal",
                    "Ordered",
                    "Reason",
                    "AISignal",
                    "AIConfidence",
                    "TechnicalSignal",
                ]
            )

        writer.writerow(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ticker,
                final_signal,
                "YES" if ordered else "NO",
                reason,
                ai_signal,
                round(float(ai_confidence), 1),
                technical_signal,
            ]
        )
