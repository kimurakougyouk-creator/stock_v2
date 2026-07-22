from openpyxl import Workbook


def save_report(trades, filename):
    """バックテスト結果をExcelに保存"""

    wb = Workbook()
    ws = wb.active
    ws.title = "Backtest"

    ws.append([
        "No",
        "買い日",
        "売り日",
        "買値",
        "売値",
        "利益率(%)",
        "保有日数"
    ])

    for i, trade in enumerate(trades, start=1):
        ws.append([
            i,
            str(trade["buy_date"].date()),
            str(trade["sell_date"].date()),
            round(trade["buy_price"], 2),
            round(trade["sell_price"], 2),
            round(trade["profit"], 2),
            trade["hold_days"]
        ])
   
    # ===== バックテスト結果サマリー =====
    ws["I1"] = "バックテスト結果"
    ws["I2"] = "総取引回数"
    ws["J2"] = len(trades)

    win_count = sum(1 for t in trades if t["profit"] > 0)
    win_rate = (win_count / len(trades) * 100) if trades else 0

    ws["I3"] = "勝率"
    ws["J3"] = f"{win_rate:.1f}%"

    total_profit = sum(t["profit"] for t in trades)
    ws["I4"] = "総利益率"
    ws["J4"] = f"{total_profit:.2f}%"

    avg_hold = (
        sum(t["hold_days"] for t in trades) / len(trades)
        if trades else 0
    )

    ws["I5"] = "平均保有日数"
    ws["J5"] = f"{avg_hold:.1f}日"

    wb.save(filename)

    print(f"Excel保存完了: {filename}")
