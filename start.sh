#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")"

echo "stock_v2を起動します（実注文は行いません）。"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python3が見つかりません。ChromebookのLinux環境でPython3をインストールしてください。"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "初回の仮想環境を作成しています..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "必要なライブラリを確認しています..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ ! -f ".env" ] || ! python setup_wizard.py --check >/dev/null 2>&1; then
  python setup_wizard.py
fi

set -a
# shellcheck disable=SC1091
if [ -f .env ]; then
  source .env
fi
set +a

echo "バックテストを開始します..."
python main_simple_step8.py

echo "最新シグナル判定を開始します..."
python -m signal_runner

echo "ダッシュボードを生成します..."
python -m dashboard

echo "BUY・SELL候補ダッシュボードを生成します..."
python -m candidate_dashboard

echo "変更追跡を実行します..."
python -m change_tracker
