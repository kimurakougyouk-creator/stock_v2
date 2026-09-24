#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "=== stock_v2 初回セットアップを開始します ==="

TRUSTED_PYTHON="/usr/bin/python3"
if [[ ! -x "$TRUSTED_PYTHON" ]]; then
  echo "FATAL: trusted Python $TRUSTED_PYTHON is unavailable." >&2
  exit 2
fi

if [[ ! -d .venv ]]; then
  echo "仮想環境 .venv を作成します。"
  "$TRUSTED_PYTHON" -m venv .venv
else
  echo "既存の仮想環境 .venv を使用します。"
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "FATAL: .venv/bin/python is unavailable." >&2
  exit 2
fi
VENV_PYTHON_REAL="$(/usr/bin/readlink -f -- .venv/bin/python)"
TRUSTED_PYTHON_REAL="$(/usr/bin/readlink -f -- "$TRUSTED_PYTHON")"
if [[ "$VENV_PYTHON_REAL" != "$TRUSTED_PYTHON_REAL" ]]; then
  echo "FATAL: existing .venv uses a different Python interpreter. Recreate it with /usr/bin/python3." >&2
  exit 2
fi

# shellcheck disable=SC1091
source .venv/bin/activate
unset PYTHONPATH

echo "pip を更新します。"
python -m pip install --upgrade pip

echo "requirements.txt の依存関係を一括インストールします。"
python -m pip install -r requirements.txt

echo "ai_asset_platform を editable install します（通常pythonでのruntime import解決に必須）。"
python -m pip install -e .

echo "ai_asset_platform が現在のcheckoutへ解決することを fail-closed で検証します。"
python scripts/verify_exact_checkout_import.py

echo "既存テストを実行します。"
python -m pytest -q

echo "=== セットアップが完了しました ==="
