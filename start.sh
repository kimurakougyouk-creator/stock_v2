#!/usr/bin/env bash
set -Eeuo pipefail

# Re-exec once in a minimal environment before any source/git/runtime gate.
# This drops inherited exported shell functions, BASH_ENV/ENV hooks, Python
# import overrides, loader overrides, and caller-controlled command resolution.
if [[ "${AI_ASSET_START_SANITIZED:-}" != "1" ]]; then
  unset BASH_ENV ENV CDPATH PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH
  exec /usr/bin/env -i \
    AI_ASSET_START_SANITIZED=1 \
    HOME="${HOME:-}" \
    USER="${USER:-}" \
    LOGNAME="${LOGNAME:-}" \
    LANG="${LANG:-C.UTF-8}" \
    PATH="/usr/local/bin:/usr/bin:/bin" \
    PYTHONDONTWRITEBYTECODE=1 \
    /bin/bash --noprofile --norc "$0" "$@"
fi

unset BASH_ENV ENV CDPATH PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH
export PATH="/usr/local/bin:/usr/bin:/bin"
export PYTHONDONTWRITEBYTECODE=1

cd "$(dirname "$0")"

# Prove clean exact strategy source before any repository Python can import.
/bin/bash scripts/verify_strategy_source_clean.sh

echo "stock_v2を起動します（実注文は行いません）。"

if [ ! -x "/usr/bin/python3" ]; then
  echo "Python3が見つかりません。ChromebookのLinux環境でPython3をインストールしてください。"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "初回の仮想環境を作成しています..."
  /usr/bin/python3 -m venv .venv
fi

VENV_PYTHON="$PWD/.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
  echo "BLOCKED: .venv/bin/python is unavailable. No Paper or Live order was sent." >&2
  exit 2
fi

verify_exact_checkout_runtime() {
  /usr/bin/env -i \
    HOME="${HOME:-}" \
    LANG="${LANG:-C.UTF-8}" \
    PATH="/usr/local/bin:/usr/bin:/bin" \
    PYTHONDONTWRITEBYTECODE=1 \
    AI_ASSET_PYTHON_BIN="$VENV_PYTHON" \
    /bin/bash --noprofile --norc scripts/ensure_exact_checkout_runtime.sh
}

# Verify plain operational Python resolves ai_asset_platform only from this
# exact checkout before setup_wizard or any application module can run.
verify_exact_checkout_runtime

echo "必要なライブラリを確認しています..."
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r requirements.txt

if [ ! -f ".env" ] || ! "$VENV_PYTHON" setup_wizard.py --check >/dev/null 2>&1; then
  "$VENV_PYTHON" setup_wizard.py
fi

# .env is untrusted local data, never executable shell input.
if [ -f .env ]; then
  SAFE_ENV_TMP="$(/usr/bin/mktemp)"
  trap '/bin/rm -f "$SAFE_ENV_TMP"' EXIT
  if ! "$VENV_PYTHON" scripts/load_start_env.py .env > "$SAFE_ENV_TMP"; then
    echo "BLOCKED: .env could not be loaded as safe data. No Paper or Live order was sent." >&2
    exit 2
  fi
  while IFS= read -r -d '' SAFE_ENV_KEY && IFS= read -r -d '' SAFE_ENV_VALUE; do
    printf -v "$SAFE_ENV_KEY" '%s' "$SAFE_ENV_VALUE"
    export "$SAFE_ENV_KEY"
  done < "$SAFE_ENV_TMP"
  /bin/rm -f "$SAFE_ENV_TMP"
  trap - EXIT
  unset SAFE_ENV_TMP SAFE_ENV_KEY SAFE_ENV_VALUE
fi

# Re-attest after setup/pip/.env-data handling and immediately before app code.
/bin/bash scripts/verify_strategy_source_clean.sh
verify_exact_checkout_runtime

echo "バックテストを開始します..."
"$VENV_PYTHON" main_simple_step8.py

echo "最新シグナル判定を開始します..."
"$VENV_PYTHON" -m signal_runner

echo "ダッシュボードを生成します..."
"$VENV_PYTHON" -m dashboard

echo "BUY・SELL候補ダッシュボードを生成します..."
"$VENV_PYTHON" -m candidate_dashboard

echo "変更追跡を実行します..."
"$VENV_PYTHON" -m change_tracker
