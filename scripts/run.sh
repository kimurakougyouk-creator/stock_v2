#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo ".venv が見つかりません。先に bash scripts/setup.sh を実行してください。"
  exit 1
fi

bash scripts/check.sh --strict-env
python3 main_simple_step8.py
