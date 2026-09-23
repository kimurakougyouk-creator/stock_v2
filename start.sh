#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")"

# Keep the attested source tree bytecode-free for every subsequent Python process.
export PYTHONDONTWRITEBYTECODE=1

# Prove clean exact strategy source before any repository Python can import.
bash scripts/verify_strategy_source_clean.sh

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
unset PYTHONPATH PYTHONHOME
TRUSTED_PYTHON_PATH="$PATH"

# Verify that plain operational Python resolves ai_asset_platform only from
# this exact checkout before setup_wizard or any application module can run.
bash scripts/ensure_exact_checkout_runtime.sh

echo "必要なライブラリを確認しています..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ ! -f ".env" ] || ! python setup_wizard.py --check >/dev/null 2>&1; then
  python setup_wizard.py
fi

# Record the complete trusted shell-function set (the venv activation
# normally defines `deactivate`). .env may provide data variables, but it must
# not add, remove, or redefine executable shell functions.
TRUSTED_SHELL_FUNCTIONS="$(declare -f)"

set -a
# shellcheck disable=SC1091
if [ -f .env ]; then
  source .env
fi
set +a

if [[ "$(declare -f)" != "$TRUSTED_SHELL_FUNCTIONS" ]]; then
  echo "BLOCKED: .env changed shell functions; command interception is prohibited. No Paper or Live order was sent." >&2
  exit 2
fi
unset TRUSTED_SHELL_FUNCTIONS

# .env is local/ignored evidence, not part of the attested checkout. It must
# never be able to change which Python executable/package tree the runtime uses.
PATH="$TRUSTED_PYTHON_PATH"
export PATH
unset PYTHONPATH PYTHONHOME
bash scripts/ensure_exact_checkout_runtime.sh

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