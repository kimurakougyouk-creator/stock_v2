from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import csv


LOG_FILE = Path("results") / "decision_log.csv"

FIELDNAMES = [
    "Timestamp",
    "Ticker",
    "FinalSignal",
    "Ordered",
    "Reason",
    "AISignal",
    "AIConfidence",
    "TechnicalSignal",
    "Price",
    "Score",
    "Grade",
    "RSI",
    "ATR",
    "MAShort",
    "MAMiddle",
    "MALong",
    "AIScore",
    "AIProvider",
]


def _format_number(
    value: float | int | None,
    digits: int = 2,
) -> str:
    """数値をCSV保存用の文字列へ安全に変換します。"""

    if value is None:
        return ""

    try:
        number = round(float(value), digits)
    except (TypeError, ValueError):
        return ""

    return str(number)


def _upgrade_existing_log() -> None:
    """古い判断ログを現在の列構成へ自動変換します。"""

    if not LOG_FILE.exists():
        return

    with LOG_FILE.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)
        existing_fieldnames = reader.fieldnames or []
        rows: list[dict[str, Any]] = list(reader)

    if existing_fieldnames == FIELDNAMES:
        return

    with LOG_FILE.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDNAMES,
            extrasaction="ignore",
        )
        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    fieldname: row.get(fieldname, "")
                    for fieldname in FIELDNAMES
                }
            )


def log_decision(
    *,
    ticker: str,
    final_signal: str,
    ordered: bool,
    reason: str,
    ai_signal: str,
    ai_confidence: float,
    technical_signal: str,
    price: float | None = None,
    score: float | None = None,
    grade: str = "",
    rsi: float | None = None,
    atr: float | None = None,
    ma_short: float | None = None,
    ma_middle: float | None = None,
    ma_long: float | None = None,
    ai_score: float | None = None,
    ai_provider: str = "",
) -> None:
    """注文判断と分析データをCSVへ追記します。"""

    LOG_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    _upgrade_existing_log()

    file_exists = LOG_FILE.exists()

    with LOG_FILE.open(
        "a",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDNAMES,
        )

        if not file_exists:
            writer.writeheader()

        writer.writerow(
            {
                "Timestamp": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "Ticker": ticker,
                "FinalSignal": final_signal,
                "Ordered": "YES" if ordered else "NO",
                "Reason": reason,
                "AISignal": ai_signal,
                "AIConfidence": _format_number(
                    ai_confidence,
                    1,
                ),
                "TechnicalSignal": technical_signal,
                "Price": _format_number(price, 2),
                "Score": _format_number(score, 1),
                "Grade": grade,
                "RSI": _format_number(rsi, 2),
                "ATR": _format_number(atr, 2),
                "MAShort": _format_number(ma_short, 2),
                "MAMiddle": _format_number(ma_middle, 2),
                "MALong": _format_number(ma_long, 2),
                "AIScore": _format_number(ai_score, 1),
                "AIProvider": ai_provider,
            }
        )
