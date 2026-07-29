[1mdiff --git a/dashboard.py b/dashboard.py[m
[1mindex df8cfe9..9554363 100644[m
[1m--- a/dashboard.py[m
[1m+++ b/dashboard.py[m
[36m@@ -89,6 +89,37 @@[m [mdef _safe_read_trade_pnls(base_dir: Path) -> list[float]:[m
 [m
 [m
 [m
[32m+[m
[32m+[m[32mdef _safe_read_realized_trades([m
[32m+[m[32m    base_dir: Path,[m
[32m+[m[32m) -> list[dict]:[m
[32m+[m[32m    """Paper Tradingの詳細な確定取引履歴を安全に読み込む。"""[m
[32m+[m
[32m+[m[32m    path = base_dir / "paper_trade_pnls.json"[m
[32m+[m
[32m+[m[32m    if not path.exists():[m
[32m+[m[32m        return [][m
[32m+[m
[32m+[m[32m    try:[m
[32m+[m[32m        data = json.loads(path.read_text(encoding="utf-8"))[m
[32m+[m[32m    except (OSError, ValueError, TypeError):[m
[32m+[m[32m        return [][m
[32m+[m
[32m+[m[32m    if not isinstance(data, dict):[m
[32m+[m[32m        return [][m
[32m+[m
[32m+[m[32m    trades = data.get("realized_trades", [])[m
[32m+[m
[32m+[m[32m    if not isinstance(trades, list):[m
[32m+[m[32m        return [][m
[32m+[m
[32m+[m[32m    return [[m
[32m+[m[32m        trade[m
[32m+[m[32m        for trade in trades[m
[32m+[m[32m        if isinstance(trade, dict)[m
[32m+[m[32m    ][m
[32m+[m
[32m+[m
 def _safe_read_decision_report([m
     base_dir: Path,[m
 ) -> dict[str, dict[str, str]]:[m
[36m@@ -127,6 +158,56 @@[m [mdef _safe_read_decision_report([m
         return {}[m
 [m
 [m
[32m+[m
[32m+[m[32mdef calculate_trade_statistics([m
[32m+[m[32m    realized_trades: list[dict],[m
[32m+[m[32m) -> list[dict]:[m
[32m+[m[32m    """銘柄別の実現損益を集計する。"""[m
[32m+[m
[32m+[m[32m    stats: dict[str, dict] = {}[m
[32m+[m
[32m+[m[32m    for trade in realized_trades:[m
[32m+[m[32m        ticker = str(trade.get("ticker", "")).strip()[m
[32m+[m[32m        if not ticker:[m
[32m+[m[32m            continue[m
[32m+[m
[32m+[m[32m        pnl = float(trade.get("realized_pnl", 0.0))[m
[32m+[m
[32m+[m[32m        item = stats.setdefault([m
[32m+[m[32m            ticker,[m
[32m+[m[32m            {[m
[32m+[m[32m                "ticker": ticker,[m
[32m+[m[32m                "total_profit": 0.0,[m
[32m+[m[32m                "wins": 0,[m
[32m+[m[32m                "trades": 0,[m
[32m+[m[32m            },[m
[32m+[m[32m        )[m
[32m+[m
[32m+[m[32m        item["total_profit"] += pnl[m
[32m+[m[32m        item["trades"] += 1[m
[32m+[m
[32m+[m[32m        if pnl > 0:[m
[32m+[m[32m            item["wins"] += 1[m
[32m+[m
[32m+[m[32m    results = [][m
[32m+[m
[32m+[m[32m    for item in stats.values():[m
[32m+[m[32m        trades = item["trades"][m
[32m+[m[32m        item["win_rate"] = ([m
[32m+[m[32m            item["wins"] / trades * 100[m
[32m+[m[32m            if trades[m
[32m+[m[32m            else 0.0[m
[32m+[m[32m        )[m
[32m+[m[32m        results.append(item)[m
[32m+[m
[32m+[m[32m    results.sort([m
[32m+[m[32m        key=lambda x: x["total_profit"],[m
[32m+[m[32m        reverse=True,[m
[32m+[m[32m    )[m
[32m+[m
[32m+[m[32m    return results[m
[32m+[m
[32m+[m
 def build_dashboard_html(base_dir: Path | None = None) -> str:[m
     base_dir = Path(base_dir or Path("results"))[m
     base_dir.mkdir(exist_ok=True, parents=True)[m
[36m@@ -134,6 +215,8 @@[m [mdef build_dashboard_html(base_dir: Path | None = None) -> str:[m
     signal_df = _safe_read_signal_excel(base_dir)[m
     summary_info = _safe_read_summary_excel(base_dir)[m
     trade_pnls = _safe_read_trade_pnls(base_dir)[m
[32m+[m[32m    realized_trades = _safe_read_realized_trades(base_dir)[m
[32m+[m[32m    trade_statistics = calculate_trade_statistics(realized_trades)[m
     decision_report = _safe_read_decision_report(base_dir)[m
     performance = calculate_performance(trade_pnls)[m
 [m
[36m@@ -334,6 +417,26 @@[m [mdef build_dashboard_html(base_dir: Path | None = None) -> str:[m
                 ])[m
             )[m
 [m
[32m+[m[32m    trade_statistics_rows = [][m
[32m+[m
[32m+[m[32m    for rank, item in enumerate(trade_statistics, start=1):[m
[32m+[m[32m        trade_statistics_rows.append([m
[32m+[m[32m            "<tr>"[m
[32m+[m[32m            f"<td>{rank}</td>"[m
[32m+[m[32m            f"<td>{html.escape(str(item['ticker']))}</td>"[m
[32m+[m[32m            f"<td>{int(item['trades'])}</td>"[m
[32m+[m[32m            f"<td>{int(item['wins'])}</td>"[m
[32m+[m[32m            f"<td>{float(item['win_rate']):.1f}%</td>"[m
[32m+[m[32m            f"<td>{_format_currency(item['total_profit'])}</td>"[m
[32m+[m[32m            "</tr>"[m
[32m+[m[32m        )[m
[32m+[m
[32m+[m[32m    trade_statistics_html = ([m
[32m+[m[32m        "\n".join(trade_statistics_rows)[m
[32m+[m[32m        if trade_statistics_rows[m
[32m+[m[32m        else "<tr><td colspan='6'>確定取引データがありません</td></tr>"[m
[32m+[m[32m    )[m
[32m+[m
     error_items = "<li>エラー0件</li>" if not errors else "".join(f"<li>{html.escape(str(error))}</li>" for error in errors)[m
     rows_html = "\n".join(html_rows) if html_rows else "<tr><td colspan='17'>データがありません</td></tr>"[m
     summary_line = html.escape(summary_text) if summary_text else "-"[m
[36m@@ -403,6 +506,24 @@[m [mdef build_dashboard_html(base_dir: Path | None = None) -> str:[m
       <div class=\"metric\"><strong>サマリー</strong><br>{summary_line}</div>[m
     </div>[m
   </div>[m
[32m+[m[32m  <div class=\"card\">[m
[32m+[m[32m    <h2>銘柄別確定損益ランキング</h2>[m
[32m+[m[32m    <table>[m
[32m+[m[32m      <thead>[m
[32m+[m[32m        <tr>[m
[32m+[m[32m          <th>順位</th>[m
[32m+[m[32m          <th>銘柄</th>[m
[32m+[m[32m          <th>取引回数</th>[m
[32m+[m[32m          <th>勝ち数</th>[m
[32m+[m[32m          <th>勝率</th>[m
[32m+[m[32m          <th>合計実現損益</th>[m
[32m+[m[32m        </tr>[m
[32m+[m[32m      </thead>[m
[32m+[m[32m      <tbody>[m
[32m+[m[32m        {trade_statistics_html}[m
[32m+[m[32m      </tbody>[m
[32m+[m[32m    </table>[m
[32m+[m[32m  </div>[m
   <div class=\"card\">[m
     <h2>注文判断ログ集計</h2>[m
     <div class=\"grid\">[m
