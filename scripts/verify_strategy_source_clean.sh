#!/usr/bin/env bash
# Pre-Python fail-closed cleanliness gate for natural-strategy evidence/runtime.
# This script performs no broker action.
set -euo pipefail

AUDITED_PATHS=(
  src
  ':(top,glob)*.py'
  ':(top,glob)*.pyc'
  ':(top,glob)*.pyo'
  ':(top,glob)*.pyz'
  ':(top,glob)*.so'
  ':(top,glob)*.pyd'
  ':(top,glob)*.dylib'
  ':(top,glob)*/__init__.py'
  ':(top,glob)*/__init__.pyc'
  ':(top,glob)*/__init__.pyo'
  ':(top,glob)*/__init__*.so'
  ':(top,glob)*/__init__*.pyd'
  ':(top,glob)*/__init__*.dylib'
  tests
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
  scripts/load_start_env.py
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

# A root directory/symlink with the same basename as a tracked root module
# can be preferred by Python as a package (e.g. dashboard/__init__.py before
# dashboard.py). Git pathspecs catch regular package contents, but Git does
# not traverse a symlink to an external package, so reject same-name root
# symlinks explicitly.
ROOT_MODULE_SYMLINK_SHADOWS="$(
  git ls-files -- ':(top,glob)*.py' |
    while IFS= read -r module_path; do
      module_stem="${module_path%.py}"
      if [[ -L "$module_stem" ]]; then
        printf '%s\n' "$module_stem"
      fi
    done
)"
if [[ -n "$ROOT_MODULE_SYMLINK_SHADOWS" ]]; then
  echo "BLOCKED: root module symlink/package shadow is present. No Paper or Live order was sent." >&2
  exit 2
fi

# Any root-level symlink can become an import shadow for a repository or
# third-party package because the repository root participates in Python's
# normal import search. The canonical checkout contains no required root
# symlinks, so reject all of them fail-closed.
ROOT_SYMLINKS=""
shopt -s nullglob dotglob
for candidate in ./*; do
  if [[ -L "$candidate" ]]; then
    ROOT_SYMLINKS+="${candidate#./}"  git ls-files -v -- "${AUDITED_PATHS[@]}" |
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
\n'
  fi
done
shopt -u nullglob dotglob
if [[ -n "$ROOT_SYMLINKS" ]]; then
  echo "BLOCKED: root-level symlink is present in the startup import boundary. No Paper or Live order was sent." >&2
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
