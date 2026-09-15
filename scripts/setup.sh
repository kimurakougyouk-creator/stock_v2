#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "=== stock_v2 初回セットアップを開始します ==="

if [[ ! -d .venv ]]; then
  echo "仮想環境 .venv を作成します。"
  python3 -m venv .venv
else
  echo "既存の仮想環境 .venv を使用します。"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "pip を更新します。"
python -m pip install --upgrade pip

echo "requirements.txt の依存関係を一括インストールします。"
python -m pip install -r requirements.txt

echo "ai_asset_platform を editable install します（通常pythonでのruntime import解決に必須）。"
python -m pip install -e .

echo "ai_asset_platform が現在のcheckoutへ解決することを fail-closed で検証します。"
python - <<'PYCHECK'
import os
import sys

expected_dir = os.path.realpath(os.path.join(os.getcwd(), "src", "ai_asset_platform"))

try:
    import ai_asset_platform
except Exception as exc:  # noqa: BLE001 - fail-closed diagnostic, any import failure is fatal
    print(f"FATAL: ai_asset_platform を通常pythonでimportできません: {exc}", file=sys.stderr)
    raise SystemExit(1)

resolved = os.path.realpath(ai_asset_platform.__file__)
if not resolved.startswith(expected_dir + os.sep):
    print(
        "FATAL: ai_asset_platform が現在のcheckout以外から解決されました。\n"
        f"  resolved = {resolved}\n"
        f"  expected dir = {expected_dir}",
        file=sys.stderr,
    )
    raise SystemExit(1)

print(f"OK: ai_asset_platform は現在のcheckoutへ解決しました: {resolved}")
PYCHECK

echo "既存テストを実行します。"
python -m pytest -q

echo "=== セットアップが完了しました ==="
