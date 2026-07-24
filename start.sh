#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")"

echo "自動売買システムをdry-runで起動します。実注文は行いません。"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python3が見つかりません。ChromebookのLinux環境で python3 をインストールしてください。"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "仮想環境を作成しています..."
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

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export BROKER_MODE="${BROKER_MODE:-dry_run}"
export DRY_RUN_ORDER_FILE="${DRY_RUN_ORDER_FILE:-results/dry_run_orders.json}"
export LOG_DIR="${LOG_DIR:-results}"

if [ "$BROKER_MODE" != "dry_run" ] && [ "$BROKER_MODE" != "dry-run" ] && [ "$BROKER_MODE" != "paper" ]; then
  echo "実注文モードは未実装です。BROKER_MODE=dry_run にしてください。"
  exit 1
fi

echo "バックテストとdry-run注文記録を開始します..."
python main_simple_step8.py
