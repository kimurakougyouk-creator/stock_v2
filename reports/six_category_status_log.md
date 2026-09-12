# 6項目実装状況ログ

このファイルは、リポジトリの実装状況(分析・シグナル・バックテスト・資産推移・リスク管理・実運用)を日次で巡回確認し、追記していくログです。判定はドキュメントの記述ではなく、実際のコード・テストファイルの確認結果に基づきます。

---

## 2026-09-11 (JST)
- 分析: 完成 — `indicators.py` の `add_indicators()` がMA5/MA25/MA75、RSI、MACD/Signal、ATR、VOL20(20日平均出来高)を計算し、`signal_engine.py` の `determine_signal()` がこれらを直接消費している。専用の `test_indicators*.py` は見当たらないが、`tests/test_signal_engine.py` を通じて指標計算結果が間接的に検証されている。
- シグナル: 完成 — `signal_engine.py` の `determine_signal()`(BUY/SELL/HOLD判定、スコア/グレード算出、参考株数計算を含む)に加え、`src/ai_asset_platform/decision_engine/decision_engine.py`、`src/ai_asset_platform/decision/final_decision.py`、`src/ai_asset_platform/decision/signal_selector.py` が存在。`tests/test_signal_engine.py`、`tests/test_signal_selector.py`、`tests/test_final_decision.py`、`tests/test_decision_engine.py` 等で網羅的にテストされている。
- バックテスト: 完成 — ルート `backtest.py`(163行)に加え、`src/ai_asset_platform/reports/backtest_evaluator.py`、`backtest_report.py`、`backtest_report_export.py`、`backtest_selector.py`、`backtest_statistics.py`、`backtest_summary.py` を実装。`tests/test_backtest_evaluator.py`、`test_backtest_foundation.py`、`test_backtest_report.py`、`test_backtest_report_export.py`、`test_backtest_risk.py`、`test_backtest_selector.py`、`test_backtest_statistics.py`、`test_backtest_summary.py`(計8ファイル)で検証済み。`results/*_backtest.xlsx` に実行結果あり。
- 資産推移: 完成 — `src/ai_asset_platform/reports/equity_chart.py`(68行)、`equity_history.py`(122行)、`performance.py`、`performance_chart.py`、`performance_history.py`、`performance_trend.py`、および `dashboard_core.py` がエクイティカーブ/損益推移の記録・描画を実装。`tests/test_equity_chart.py`、`test_equity_history.py`、`test_dashboard_equity_curve.py`、`test_dashboard_performance_drawdown.py`、`test_dashboard_performance_health.py`、`test_dashboard_performance_trend.py` で検証。
- リスク管理: 完成(Paper運用範囲) — ルート `risk_manager.py`(参考株数・保有ポジションリスク計算)に加え、`src/ai_asset_platform/execution/shared_risk_gate.py`、`legacy_risk_gate.py`、`risk/market_sizing.py`、`execution/execution_service_risk_gate` 系を実装。`tests/test_risk_manager_position_size.py`、`test_risk_manager_portfolio_risk.py`、`test_shared_risk_gate.py`、`test_legacy_risk_gate.py`、`test_jp_lot_risk_boundaries.py`、`test_execution_service_risk_gate.py` で検証。Live側の日次リスク上限はアカウントカレンダー/タイムゾーン対応済み(PR #275、`test_account_calendar_ledger.py`)。
- 実運用: 一部実装 — Live経路の主要プリミティブ(`execution/live_pilot_single_send.py` 624行、`live_pilot_completion.py` 561行、`live_pilot_emergency_stop.py`、`live_pilot_one_shot_authorization.py`、`live_pilot_same_run_preflight.py`、`live_pilot_send_journal.py`、`live_pilot_source_cutover.py`、`brokers/ibkr_live_readonly_account.py`、`ibkr_live_all_open_orders.py`、`ibkr_live_fx_evidence.py`、`ibkr_live_postfill_evidence.py` 等)は実装済みで、`main`(SHA `c18a877`)上でCI(pytest, run #1919)はgreen。ただしGitHub上でPR #280/#281/#282(Codexセーフティ指摘の修正、Live送信/完了パス対象)が現在オープンで未マージであり、実弾送信の安全性検証はまだ進行中。Issue #255記載の外部前提(JPY入金決済、日本株取引許可、JASDEC登録、Live読み取り専用API疎通)もUNVERIFIEDのまま。CLAUDE.md/HANDOFF_MASTER.mdの安全不変条件どおり、現時点でも **NO-GO(実弾`placeOrder`不可)**。

### 前回からの変化点
初回実行のため比較対象なし。

---

## 2026-09-13 (JST)
- 分析: 完成 — 変化なし。`indicators.py` の `add_indicators()`(MA5/MA25/MA75, RSI, MACD/Signal, ATR, VOL20)、`tests/test_signal_engine.py` 経由の間接検証は前回確認時点から変更なし(`main` は前回ログ以降コミットなし)。
- シグナル: 完成 — 変化なし。`signal_engine.py` の `determine_signal()` および `src/ai_asset_platform/decision*` 系、`tests/test_signal_engine.py`/`test_signal_selector.py`/`test_final_decision.py`/`test_decision_engine.py` に変更なし。
- バックテスト: 完成 — 変化なし。`backtest.py` および `src/ai_asset_platform/reports/backtest_*.py`(evaluator/report/report_export/selector/statistics/summary)、対応する `tests/test_backtest_*.py`(8ファイル)に変更なし。
- 資産推移: 完成 — 変化なし。`src/ai_asset_platform/reports/equity_chart.py`/`equity_history.py`/`performance*.py`、`dashboard_core.py`、対応テスト群に変更なし。
- リスク管理: 完成(Paper運用範囲) — 変化なし。`risk_manager.py`、`execution/shared_risk_gate.py`/`legacy_risk_gate.py`、`risk/market_sizing.py`、対応テスト群(`test_risk_manager_*`, `test_shared_risk_gate.py`, `test_jp_lot_risk_boundaries.py` 等)に変更なし。
- 実運用: 一部実装 — `main`(SHA `b854243`)は前回ログ以降コミットなし。GitHub上でPR #280/#281/#282(Live送信・完了パスに対するCodexセーフティ指摘の修正)は依然オープンかつ未マージ。特にPR #281は本日(2026-09-12 UTC)もCodexとのレビューサイクルが継続中で、直近コメント(2026-09-12T20:42:37Z)ではCodex側が `live_operational_pilot_readiness.py`/`live_pilot_same_run_preflight.py`/`ibkr_live_postfill_evidence.py` に対する追加の fail-closed 修正(アカウントfingerprint照合、Paper HEALTHY契約の完全化、`open_order_count` の厳密int判定、`cancel_sent` 等の明示的False判定、通貨バインド)を実装したと報告しているが、**Codex側の実行環境にGitリモートが設定されておらずGitHub上のPRブランチへは実際にはプッシュされていない**(PRの実HEAD SHAは引き続き `1a930b83e83786d6ac5dc73ba38add7a265eaacd` のまま、CIも2026-09-10時点のgreenが最新でこの提案分は未検証)。CLAUDE.mdが警告する「stale or mixed evidence」に該当するため、この修正提案はUNVERIFIEDとして扱う。Issue #255のチェックリストは1項目も完了(チェック)されておらず、外部前提(JPY入金決済、日本株取引許可、JASDEC登録、Live読み取り専用API疎通)も引き続きUNVERIFIED。CLAUDE.md/HANDOFF_MASTER.mdの安全不変条件どおり、現時点でも **NO-GO(実弾`placeOrder`不可)**。

### 前回からの変化点
コード面(`main`)に変更なし。GitHub上ではPR #281のCodexレビュー往復が本日も継続し、追加の fail-closed 修正案が提示されたが、Codex実行環境のGit remote未設定によりPRブランチへの実プッシュは行われておらず、GitHub上のPR実HEADは前回確認時から変化していない(未反映のまま)。Issue #255はNO-GO状態を維持。
