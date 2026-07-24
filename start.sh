#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "初回セットアップを行います。"
  bash setup.sh
fi

if [ ! -f ".env" ]; then
  echo "メールの初回設定を行います。"
  source .venv/bin/activate
  python setup_mail.py
fi

# 保存済みのメール設定を読み込みます。
set -a
source .env
set +a

source .venv/bin/activate

echo
 echo "自動売買システムを開始します。"
python main_simple_step8.py

echo
 echo "処理が完了しました。"
