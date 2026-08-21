#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "ERROR: .venv is missing. Run: bash scripts/setup.sh"
  exit 1
fi

source .venv/bin/activate

# Load local environment values when present. .env is ignored by Git.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

exec bash start.sh
