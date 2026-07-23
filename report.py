from openpyxl import Workbook


def save_report(trades, filename, result=None):
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
        "売却理由",
        "株数",
        "リスク額(円)",
        "資金使用率(%)",
        "利益率(%)",
        "手数料込み利益率(%)",
        "損益(円)",
        "手数料(円)",
        "決済後資産(円)",
        "保有日数"
    ])

    for i, trade in enumerate(trades, start=1):
        ws.append([
            i,
            str(trade["buy_date"].date()),
            str(trade["sell_date"].date()),
            round(trade["buy_price"], 2),
            round(trade["sell_price"], 2),
            trade.get("exit_reason", ""),
            round(trade.get("shares", 0), 4),
            round(trade.get("risk_amount", 0), 0),
            round(trade.get("capital_usage", 0), 2),
            round(trade.get("gross_profit", trade["profit"]), 2),
            round(trade["profit"], 2),
            round(trade.get("net_profit_yen", 0), 0),
            round(trade.get("commission", 0), 0),
            round(trade.get("capital", 0), 0),
            trade["hold_days"]
        ])

    ws["N1"] = "バックテスト結果"
    ws["N2"] = "総取引回数"
    ws["O2"] = len(trades)

    win_count = sum(1 for t in trades if t["profit"] > 0)
    win_rate = (win_count / len(trades) * 100) if trades else 0

    ws["N3"] = "勝率"
    ws["O3"] = f"{win_rate:.1f}%"

    total_profit = result["total_profit"] if result else sum(t["profit"] for t in trades)
    ws["N4"] = "総利益率"
    ws["O4"] = f"{total_profit:.2f}%"

    avg_hold = sum(t["hold_days"] for t in trades) / len(trades) if trades else 0
    ws["N5"] = "平均保有日数"
    ws["O5"] = f"{avg_hold:.1f}日"

    if result:
        ws["N6"] = "最終資産"
        ws["O6"] = round(result["final_capital"], 0)
        ws["N7"] = "手数料込み利益"
        ws["O7"] = round(result["net_profit_yen"], 0)
        ws["N8"] = "総手数料"
        ws["O8"] = round(result["total_commission"], 0)
        ws["N9"] = "最大ドローダウン"
        ws["O9"] = f"{result['max_drawdown']:.2f}%"

        curve_ws = wb.create_sheet("AssetCurve")
        curve_ws.append(["日付", "資産(円)", "ドローダウン(%)"])
        for point in result.get("asset_curve", []):
            date = point["date"]
            curve_ws.append([
                str(date.date()) if hasattr(date, "date") else str(date),
                round(point["capital"], 0),
                round(point.get("drawdown", 0), 2),
            ])

    wb.save(filename)

    print(f"Excel保存完了: {filename}")
