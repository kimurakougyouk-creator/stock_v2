# stock_v2

日本株向けのバックテスト、パラメータ最適化、レポート出力、dry-run模擬注文を扱う検証用プロジェクトです。現時点では実注文を出さず、dry-runで安全に注文内容を確認することを最優先にしています。

## 主な構成

- `main_simple_step8.py`: `tickers.csv` を読み込み、株価取得、指標計算、最適化、レポート作成、dry-run注文記録を実行する現在のエントリーポイントです。
- `auto_trading_engine.py`: バックテスト結果の売買シグナルから注文を作成し、`BrokerFactory` 経由で `DryRunBroker` に渡します。dry-run以外は安全停止します。
- `indicators.py`: 移動平均、RSI、MACD、ATR、出来高平均を追加します。
- `strategy.py`: 買いシグナルを作成します。中期移動平均が上向きであることも条件に含めています。
- `backtest.py`: 手数料、スリッページ、利益確定、損切り、ATRトレーリング、資金管理、100株単位のポジションサイズを考慮してバックテストします。
- `optimizer.py`: ATR倍率、移動平均期間、RSI、利益確定率、損切り率を組み合わせ、最低売買回数を満たす最適設定を選びます。
- `report.py`: 取引明細、資金推移、ドローダウン、手数料、最終資産をExcelへ保存します。
- `execution.py`: `BrokerInterface`、`BrokerFactory`、`DryRunBroker`、注文検証、dry-run注文記録を提供します。
- `sbi_broker.py`: 将来のSBI証券接続用の土台です。認証・発注・取消・残高取得・保有銘柄取得は未実装で、呼び出すと安全に `NotImplementedError` になります。
- `stability.py`: 日付別ログ、リトライ、例外ログ、安全停止を共通化します。
- `startup.py`: 起動時セルフチェックを行い、dry-run以外の運用開始を防ぎます。

## dry-runと将来の証券会社接続

現在は実注文を出しません。`BrokerFactory.create("dry_run")` は `DryRunBroker` を返し、模擬注文をJSONへ記録します。

`BrokerFactory.create("sbi")` は `SbiBroker` の土台を返しますが、認証・注文送信・注文取消・残高取得・保有銘柄取得は未実装です。アプリ起動時のセルフチェックと `auto_trading_engine.py` は dry-run以外を安全停止するため、現時点で実注文は実行されません。

## Chromebookでの実行

Chromebook の Linux 開発環境で実行する場合は、`CHROMEBOOK_RUNBOOK.md` の手順に従ってください。依存関係は `requirements.txt` に整理しています。

## テストと静的チェック

```bash
python3 -m pytest -q
python3 -m py_compile $(git ls-files '*.py')
ruff check .
```

## 注意

- Gmailアプリパスワードなどの秘密情報はコードに保存しないでください。
- 現在の注文実行はdry-run専用です。実際の証券会社ログイン・本注文処理はまだありません。
- 運用前に `OPERATIONS_CHECKLIST.md` を確認してください。
