from ai_asset_platform.reports.decision_log_report import (
    LOG_FILE,
    REPORT_FILE,
    generate_decision_log_report,
)

__all__ = ["LOG_FILE", "REPORT_FILE", "generate_decision_log_report"]


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
