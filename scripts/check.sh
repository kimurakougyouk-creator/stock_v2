#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

STRICT_ENV=0
if [[ "${1:-}" == "--strict-env" ]]; then
  STRICT_ENV=1
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

python3 -m py_compile $(git ls-files '*.py')
pytest -q
python3 - <<'PY'
import importlib
import sys
import types


class _DummyWorkbook:
    pass


def _install_missing_stub(name, module):
    try:
        importlib.import_module(name)
    except ModuleNotFoundError:
        sys.modules[name] = module


_install_missing_stub("pandas", types.SimpleNamespace())
_install_missing_stub("yfinance", types.SimpleNamespace())
_install_missing_stub("openpyxl", types.SimpleNamespace(Workbook=_DummyWorkbook))
_install_missing_stub("matplotlib", types.SimpleNamespace())
sys.modules.setdefault("matplotlib.pyplot", types.SimpleNamespace())

modules = [
    "backtest",
    "config",
    "indicators",
    "mail",
    "main_simple_step8",
    "optimizer",
    "report",
    "strategy",
]

for module in modules:
    importlib.import_module(module)

print("主要ファイルのimport確認が完了しました。")
PY

missing=0
for name in EMAIL_ADDRESS APP_PASSWORD; do
  if [[ -z "${!name:-}" ]]; then
    echo "${name} が未設定です。メール送信または本番実行前に環境変数か .env に設定してください（値は表示しません）。"
    missing=1
  else
    echo "${name} は設定済みです（値は表示しません）。"
  fi
done

if [[ "$STRICT_ENV" -eq 1 && "$missing" -ne 0 ]]; then
  exit 1
fi
