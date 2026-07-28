from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any


LOG_FILE = Path("results") / "decision_log.csv"
REPORT_FILE = Path("results") / "decision_log_report.csv"


def generate_decision_log_report(
    log_file: Path = LOG_FILE,
    report_file: Path = REPORT_FILE,
) -> dict[str, Any]:
    """注文判断ログを集計し、CSVレポートを作成します。"""

    if not log_file.exists():
        raise FileNotFoundError(
            f"判断ログが見つかりません: {log_file}"
        )

    with log_file.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        rows = list(csv.DictReader(file))

    total_decisions = len(rows)
    ordered_count = sum(
        row.get("Ordered", "").strip().upper() == "YES"
        for row in rows
    )
    not_ordered_count = total_decisions - ordered_count

    final_signal_counts = Counter(
        row.get("FinalSignal", "").strip().upper() or "UNKNOWN"
        for row in rows
    )

    ticker_counts = Counter(
        row.get("Ticker", "").strip() or "UNKNOWN"
        for row in rows
    )

    confidence_values: list[float] = []

    for row in rows:
        value = row.get("AIConfidence", "").strip()

        if not value:
            continue

        try:
            confidence_values.append(float(value))
        except ValueError:
            continue

    average_ai_confidence = (
        round(
            sum(confidence_values) / len(confidence_values),
            1,
        )
        if confidence_values
        else 0.0
    )

    order_rate = (
        round(ordered_count / total_decisions * 100, 1)
        if total_decisions
        else 0.0
    )

    summary: dict[str, Any] = {
        "total_decisions": total_decisions,
        "ordered_count": ordered_count,
        "not_ordered_count": not_ordered_count,
        "order_rate": order_rate,
        "average_ai_confidence": average_ai_confidence,
        "final_signal_counts": dict(final_signal_counts),
        "ticker_counts": dict(ticker_counts),
    }

    report_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with report_file.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.writer(file)

        writer.writerow(
            [
                "Category",
                "Item",
                "Value",
            ]
        )

        writer.writerow(
            [
                "Summary",
                "TotalDecisions",
                total_decisions,
            ]
        )
        writer.writerow(
            [
                "Summary",
                "OrderedCount",
                ordered_count,
            ]
        )
        writer.writerow(
            [
                "Summary",
                "NotOrderedCount",
                not_ordered_count,
            ]
        )
        writer.writerow(
            [
                "Summary",
                "OrderRatePercent",
                order_rate,
            ]
        )
        writer.writerow(
            [
                "Summary",
                "AverageAIConfidence",
                average_ai_confidence,
            ]
        )

        for signal, count in sorted(
            final_signal_counts.items()
        ):
            writer.writerow(
                [
                    "FinalSignal",
                    signal,
                    count,
                ]
            )

        for ticker, count in sorted(
            ticker_counts.items()
        ):
            writer.writerow(
                [
                    "Ticker",
                    ticker,
                    count,
                ]
            )

    return summary


if __name__ == "__main__":
    result = generate_decision_log_report()

    print("判断ログ集計レポートを作成しました。")
    print(f"判断件数: {result['total_decisions']}")
    print(f"注文実行件数: {result['ordered_count']}")
    print(f"注文実行率: {result['order_rate']}%")
    print(
        "AI平均信頼度: "
        f"{result['average_ai_confidence']}"
    )
    print(f"出力先: {REPORT_FILE}")
