# decision_log.csv テスト汚染 監査記録

作成日時: 2026-10-24
作成者: Claude Code (PM/実装責任者)
関連PR: #359 (squash merge済み, main SHA dee38a57a564d8a9cfd2fe7b40fd30b68d7f07b4)

## 1. 原本ファイル（無変更・保全）

| 項目 | 値 |
| --- | --- |
| パス | `results/decision_log.csv` |
| サイズ | 258,880 bytes |
| SHA-256 | `4d6c06400002fee68ecdbea5f8144e8a9a6add438dce8196b5be8c69f0520312` |
| 全行数（ヘッダー含む） | 1327行 |
| データ行数 | 1326行 |
| ヘッダー | `Timestamp,Ticker,FinalSignal,Ordered,Reason,AISignal,AIConfidence,TechnicalSignal,Price,Score,Grade,RSI,ATR,MAShort,MAMiddle,MALong,AIScore,AIProvider`（UTF-8 BOM付き） |
| 最終更新時刻 | 2026-10-24 06:29:28 (JST) |
| 保全コピー | `results/decision_log_original_preserved_2026-10-24.csv`（同一SHA-256、読み取り専用属性を設定済み） |

本監査作業を通じて原本ファイルへの編集・削除・上書きは一切行っていない（上記SHA-256は本監査開始時と完了時で不変であることを確認済み）。

## 2. テスト由来行の識別規則

列の組み合わせ `Ticker == "7203.T" AND AIProvider == "test"` を汚染行の判定規則として採用した。

根拠:
- `"7203.T"` は、本番の実運用ティッカー（AAPL/SPY/9432.T）には存在しない、テストファイル内で固定的に使われるダミーティッカーである。
- `AIProvider == "test"` は、signal_runner.py 内で `judge_with_ai()` が返す `SimpleNamespace(..., provider="test", ...)` というテスト専用のモック値そのものであり、実際のAIプロバイダ（none/gemini等）には絶対に現れない値である。
- 全1326データ行を `Ticker` と `AIProvider` の2軸で突合した結果、この規則に当てはまらない行（例: `Ticker=7203.T` だがprovider≠test、または `AIProvider=test` だがticker≠7203.T）は **0件** であった。すなわち本規則は1326行全体に対して排他的・完全に分割可能であり、「不明・境界」に該当する行は存在しない。

| 分類 | 件数 |
| --- | --- |
| `Ticker=7203.T` の行 | 1281 |
| `AIProvider=test` の行 | 1281 |
| 両方同時に満たす行 | 1281（完全一致） |
| `Ticker=7203.T` だが provider≠test | 0 |
| `AIProvider=test` だが ticker≠7203.T | 0 |

実データ行のティッカー内訳: AAPL 15件 / SPY 15件 / 9432.T 15件（計45件）。
実データ行のAIProvider内訳: `none` 38件 / `gemini` 7件（計45件、いずれもテスト由来ではない）。

## 3. 根本原因（コード経路、読み取り専用で特定）

`signal_runner.run_signal_scan()` は評価した各ティッカーについて無条件に `log_decision()` を呼ぶ（signal_runner.py:1085）。
`tests/test_signal_runner_time_stop.py`（6テスト関数）と `tests/test_signal_runner_final_decision.py`（28テスト関数）が、この呼び出しを一度もモックせずに `run_signal_scan(["7203.T"], ...)` を実行していたため、pytest実行のたびに本番の `results/decision_log.csv` へ直接書き込んでいた。
（`tests/test_signal_runner.py` は `monkeypatch.chdir(tmp_path)` により安全に隔離されており無関係と確認済み。）

## 4. 既報告の5行との関係

2026-10-23 16:02:09〜16:02:10 に記録された当初報告の5行（現ファイルの1221〜1225行目）は、下記「5. 除外範囲」のうち `1094-1225` という連続範囲の末尾に含まれる。すなわち、これらは独立した別インシデントではなく、2026-09-27から続いていた同一の長期的テスト汚染（計1182行、〜2026-10-23時点）の一部であったことが、今回の全件監査で確定した。

## 5. 除外範囲（行番号、原本ファイル基準、ヘッダーを1行目として1-indexed）

連続した8つの範囲に分割される（計1281行）:

```
2-100
110-274
278-475
482-811
821-913
917-1081
1094-1225   ← 既報告5行（1221-1225）はこの範囲の末尾
1229-1327   ← 下記6.の自己発生分（99行）
```

## 6. 2026-10-24の自己発生インシデント（別枠で開示）

本修正（PR #359）の検証作業中、最初に試した隔離方式（`decision_logger.LOG_FILE` のmonkeypatch）がモジュール分裂により機能せず、2026-10-24 06:26:30〜06:29:28 の間に新たな99行（現ファイルの1229〜1327行目、AAPL/SPYの正常行である1226-1228行目の直後）が本番ファイルに追加された。この欠陥方式は本番適用前に破棄し、`signal_runner.log_decision` 属性を直接差し替える方式（PR #359でマージ済み）に修正済みである。この99行は上記の識別規則（Ticker=7203.T, AIProvider=test）に完全に合致するため、他の historical 1182行と同一の規則で機械的に除外されている。

## 7. 訂正版（分析用）CSV

| 項目 | 値 |
| --- | --- |
| パス | `results/decision_log_analysis_cleaned.csv` |
| SHA-256 | `79e8804012d9815d9a97473448e75be631754a2e353c9f3a61fe007792b2060b` |
| 全行数（ヘッダー含む） | 46行 |
| データ行数 | 45行（AAPL 15 / SPY 15 / 9432.T 15） |
| 列構造・文字コード | 原本と同一（UTF-8 BOM付き、同一ヘッダー、同一列順） |
| データ期間 | 2026-10-01 16:41:45 〜 2026-10-24 04:32:48 |

## 8. 行数整合性の検証

- 原本データ行数（1326） = 除外行数（1281） + 採用行数（45） → 一致を確認済み。
- 除外規則に重複判定は存在しない（単一の論理積条件のみ、OR結合なし）。
- 採用した45行はいずれも実行コード経路（`run_verified_paper_runtime_once()` 等）由来の本物の判断記録であり、テストのモック値では再現し得ない値（実際の市場終値、実際のAI応答テキスト等)を含むことを目視確認済み。
- 本監査は decision_log.csv / decision_log_analysis_cleaned.csv の読み取り・新規ファイル作成のみであり、既存のbroker約定証拠（`results/ibkr_verified_paper_runtime_history.jsonl`、gen5 Live pilot journal等）には一切アクセス・変更していない。影響なし。
