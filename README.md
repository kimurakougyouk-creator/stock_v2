# stock_v2

日本株向けのバックテスト、パラメータ最適化、レポート出力、dry-run模擬注文を扱う検証用プロジェクトです。

## 主な構成

- `main_simple_step8.py`: `tickers.csv` を読み込み、株価取得、指標計算、最適化、レポート作成、dry-run注文記録を実行します。
- `indicators.py`: 移動平均、RSI、MACD、ATR、出来高平均を追加します。
- `strategy.py`: 買いシグナルを作成します。中期移動平均が上向きであることも条件に含めています。
- `backtest.py`: 手数料、スリッページ、利益確定、損切り、ATRトレーリング、資金管理、100株単位のポジションサイズを考慮してバックテストします。
- `optimizer.py`: ATR倍率、移動平均期間、RSI、利益確定率、損切り率を組み合わせ、最低売買回数を満たす最適設定を選びます。
- `report.py`: 取引明細、資金推移、ドローダウン、手数料、最終資産をExcelへ保存します。
- `execution.py`: `BrokerInterface`、`BrokerFactory`、`DryRunBroker`、注文検証、dry-run注文記録を提供します。
- `stability.py`: 日付別ログ、リトライ、例外ログ、安全停止を共通化します。

## dry-runと将来の証券会社接続

現在は実注文を出しません。`BrokerFactory.create("dry_run")` は `DryRunBroker` を返し、模擬注文をJSONへ記録します。

SBI証券などの実注文モードは未実装です。`BrokerFactory.create("sbi")` や `BrokerFactory.create("live")` を選ぶと、安全のため `NotImplementedError` で停止します。将来の証券会社接続は `BrokerInterface` を実装するクラスを追加する方針です。

## テスト

```bash
python3 -m pytest -q
python3 -m py_compile stability.py tests/test_stability.py execution.py tests/test_execution.py backtest.py optimizer.py report.py main_simple_step8.py strategy.py tests/test_backtest_foundation.py tests/test_strategy.py
```

## 注意

- Gmailアプリパスワードなどの秘密情報はコードに保存しないでください。
- 現在の注文実行はdry-run専用です。実際の証券会社ログイン・本注文処理はまだありません。
