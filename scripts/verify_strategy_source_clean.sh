#!/usr/bin/env bash
# Pre-Python fail-closed cleanliness gate for natural-strategy evidence/runtime.
# This script performs no broker action.
set -euo pipefail

AUDITED_PATHS=(
  src
  ai_asset_platform
  ai_asset_platform.py
  signal_runner.py
  config.py
  requirements.txt
  pyproject.toml
  pytest.ini
  start.sh
  scripts/run.sh
  scripts/verify_strategy_source_clean.sh
  scripts/ensure_exact_checkout_runtime.sh
  scripts/verify_exact_checkout_import.py
  ibkr_verified_paper_runtime_once.sh
  ibkr_strategy_profitability_evidence_once.sh
  strategy_promotion_policy_once.sh
  config
  sitecustomize.py
  sitecustomize.pyc
  usercustomize.py
  usercustomize.pyc
)

ACTUAL_SHA="$(git rev-parse HEAD)"
if [[ ! "$ACTUAL_SHA" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "BLOCKED: exact strategy source SHA is unavailable. No Paper or Live order was sent." >&2
  exit 2
fi

SOURCE_DIRTY="$(
  git status --porcelain=v1 --untracked-files=all -- "${AUDITED_PATHS[@]}"
)"
if [[ -n "$SOURCE_DIRTY" ]]; then
  echo "BLOCKED: tracked or untracked strategy source changes are present before Python launch. No Paper or Live order was sent." >&2
  exit 2
fi

INDEX_HIDDEN="$(
  git ls-files -v -- "${AUDITED_PATHS[@]}" |
    awk '$1 == "S" || $1 ~ /^[a-z]$/ { print }'
)"
if [[ -n "$INDEX_HIDDEN" ]]; then
  echo "BLOCKED: strategy source contains assume-unchanged or skip-worktree entries. No Paper or Live order was sent." >&2
  exit 2
fi

IGNORED_IMPORTABLE="$(
  git ls-files --others --ignored --exclude-standard -- "${AUDITED_PATHS[@]}" |
    while IFS= read -r path; do
      if [[ -L "$path" ]]; then
        printf '%s\n' "$path"
        continue
      fi
      case "$path" in
        *.py|*.pyc|*.pyo|*.pyz|*.so|*.pyd|*.dylib)
          printf '%s\n' "$path"
          ;;
        *)
          if [[ -d "$path" ]] && {
            [[ -f "$path/__init__.py" ]] ||
            [[ -f "$path/__init__.pyc" ]] ||
            compgen -G "$path/__init__*.so" > /dev/null
          }; then
            printf '%s\n' "$path"
          fi
          ;;
      esac
    done
)"
if [[ -n "$IGNORED_IMPORTABLE" ]]; then
  echo "BLOCKED: ignored importable artifact/package/symlink is present in strategy source paths. No Paper or Live order was sent." >&2
  exit 2
fi

printf 'STRATEGY_SOURCE_SHA=%s\n' "$ACTUAL_SHA"
