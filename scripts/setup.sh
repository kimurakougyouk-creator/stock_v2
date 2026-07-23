#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p results

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  echo ".env を作成しました。メール送信を使う場合は必要な環境変数を設定してください（値は表示しません）。"
fi

bash scripts/check.sh
