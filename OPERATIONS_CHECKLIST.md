# 運用開始チェックリスト

## Chromebook起動前

- [ ] Linux 開発環境（Crostini）が有効になっている。
- [ ] `python3 -m venv .venv` で仮想環境を作成済み。
- [ ] `source .venv/bin/activate` で仮想環境を有効化済み。
- [ ] `python -m pip install -r requirements.txt` が成功している。

## 起動前

- [ ] `BROKER_MODE=dry_run` になっている。
- [ ] `DRY_RUN=True` になっている。
- [ ] 実注文モードを選択していない。
- [ ] `tickers.csv` が存在し、対象銘柄が入っている。
- [ ] `results/` に書き込みできる。
- [ ] Gmail通知を使う場合のみ、環境変数 `APP_PASSWORD` を設定している。
- [ ] Gmailアプリパスワードや証券会社パスワードをコードに保存していない。
- [ ] `python -m pytest -q` が成功している。
- [ ] `python -m py_compile $(git ls-files '*.py')` が成功している。
- [ ] `ruff check .` が成功している。

## 起動時

- [ ] 起動時セルフチェックが成功する。
- [ ] `results/startup_YYYY-MM-DD.log` を確認する。
- [ ] `results/auto_trading_engine_YYYY-MM-DD.log` を確認する。
- [ ] `results/dry_run_orders_YYYY-MM-DD.log` を確認する。

## 実行後

- [ ] `summary_report.xlsx` が作成されている。
- [ ] 各銘柄のレポートに売買理由、株数、リスク額、資金使用率が記録されている。
- [ ] dry-run注文JSONに想定外の重複注文がない。
- [ ] エラーがある場合はログに原因が残っている。

## SBI証券接続前

- [ ] `sbi_broker.py` の認証・注文送信・注文取消・残高取得・保有銘柄取得を実装する前に、dry-runのテストをすべて通す。
- [ ] ログイン情報は必ず環境変数または安全なシークレット管理で扱う。
- [ ] 本注文前にdry-runで注文内容を十分に検証する。
- [ ] 実注文を有効化する前に、`startup.py` と `auto_trading_engine.py` の安全停止条件を見直す。
