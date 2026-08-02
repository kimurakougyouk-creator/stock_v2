from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PaperTradingLogIntegrity:
    before_count: int
    after_count: int
    expected_added: int
    actual_added: int
    is_valid: bool
    message: str


def count_decision_log_rows(
    log_file: Path,
) -> int:
    """判断ログのデータ行数を数える。"""

    if not log_file.exists():
        return 0

    with log_file.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)
        return sum(1 for _ in reader)


def evaluate_log_integrity(
    *,
    before_count: int,
    after_count: int,
    expected_added: int,
) -> PaperTradingLogIntegrity:
    """Paper Trading実行前後のログ件数を検証する。"""

    actual_added = after_count - before_count
    is_valid = actual_added == expected_added

    if is_valid:
        message = (
            f"判断ログは正常です。"
            f"{actual_added}件追加されました。"
        )
    else:
        message = (
            "判断ログ件数が想定と一致しません。"
            f"想定追加={expected_added}件 / "
            f"実際追加={actual_added}件"
        )

    return PaperTradingLogIntegrity(
        before_count=before_count,
        after_count=after_count,
        expected_added=expected_added,
        actual_added=actual_added,
        is_valid=is_valid,
        message=message,
    )
