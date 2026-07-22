from openpyxl import Workbook


def save_report(trades, filename):
    """バックテスト結果をExcelに保存"""

    wb = Workbook()
    ws = wb.active
    ws.title = "Backtest"

    ws.append([
        "買い日",
        "売り日",
        "買値",
        "売値",
        "利益率(%)"
    ])

    for trade in trades:
        ws.append([
            str(trade["buy_date"].date()),
            str(trade["sell_date"].date()),
            trade["buy_price"],
            trade["sell_price"],
            round(trade["profit"], 2)
        ])
   
    wb.save(filename)

    print(f"Excel保存完了: {filename}")
