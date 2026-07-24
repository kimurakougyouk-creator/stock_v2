# Chromebook実行手順

この手順は、Chromebook の Linux 開発環境（Crostini）で `develop-auto-trading` を dry-run として動かすためのものです。現時点では実注文を出しません。

## 1. Linux環境の準備

Chromebook の「設定」→「デベロッパー」→「Linux 開発環境」を有効化します。ターミナルを開き、以下を実行します。

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```

## 2. リポジトリ取得

```bash
git clone https://github.com/kimurakougyouk-creator/stock_v2.git
cd stock_v2
git checkout develop-auto-trading
```

すでに取得済みの場合は、以下で最新化します。

```bash
cd stock_v2
git checkout develop-auto-trading
git pull
```

## 3. ワンクリック起動

2回目以降は以下だけで起動できます。初回は `.venv` 作成、依存関係インストール、メール設定ウィザード起動、`.env` 読み込み、`main_simple_step8.py` 実行まで自動で行います。

```bash
bash start.sh
```

Gmail通知を使う場合だけ、初回ウィザードに従って Gmailアドレスとアプリパスワードを入力してください。入力内容は `.env` に保存され、GitHubには保存されません。Gmail通知が不要な場合は、メール送信は安全にスキップされます。

## 4. 手動で確認したい場合

`start.sh` は内部で以下と同等の処理を行います。問題切り分け時だけ手動実行してください。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python setup_wizard.py
python main_simple_step8.py
```

## 5. 実行前チェック

```bash
python -m pytest -q
python -m py_compile $(git ls-files '*.py')
ruff check .
```

`tickers.csv` に対象銘柄があることも確認します。

```bash
cat tickers.csv
```

## 6. dry-run実行

通常は以下だけを使います。

```bash
bash start.sh
```

## 7. 実行後に確認するファイル

- `summary_report.xlsx`
- `{銘柄}_report.xlsx`
- `{銘柄}_settings.xlsx`
- `results/dry_run_orders.json`
- `results/startup_YYYY-MM-DD.log`
- `results/auto_trading_engine_YYYY-MM-DD.log`
- `results/dry_run_orders_YYYY-MM-DD.log`

## 8. よくある問題

- Yahoo Finance の株価取得が失敗する場合は、Chromebook のネットワーク、プロキシ、DNS、時刻設定を確認してください。
- `ModuleNotFoundError` が出る場合は、仮想環境が有効か、`python -m pip install -r requirements.txt` が成功しているか確認してください。
- Gmail送信が不要なら `APP_PASSWORD` は未設定で問題ありません。送信はスキップされます。
