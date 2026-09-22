#!/usr/bin/env bash
set -euo pipefail

# Human-facing single entrypoint for Issue #255.
#
# This wrapper never creates an authorization and never supplies the final
# consequential confirmation by default. Those values must already exist in
# the environment from the separately approved operator step.
#
# Re-running this same entrypoint after the irreversible campaign marker exists
# is recovery-only: the Python coordinator makes the sender unreachable and
# performs read-only reconciliation only.

ROOT="${AI_ASSET_PLATFORM_ROOT:-$PWD}"
cd "$ROOT"

VENV_PYTHON_LINK="$ROOT/.venv/bin/python"
if [[ ! -L "$VENV_PYTHON_LINK" ]]; then
  echo "BLOCKED: .venv Python must be a symlink to an attested system interpreter. No Live order was sent."
  exit 2
fi
if [[ ! -x /usr/bin/readlink || ! -x /usr/bin/stat ]]; then
  echo "BLOCKED: system runtime attestation tools are unavailable. No Live order was sent."
  exit 2
fi
TRUSTED_PYTHON_REAL="$(/usr/bin/readlink -f -- "$VENV_PYTHON_LINK")" || {
  echo "BLOCKED: .venv Python target cannot be resolved. No Live order was sent."
  exit 2
}
if [[ ! "$TRUSTED_PYTHON_REAL" =~ ^/usr/bin/python3(\.[0-9]+)?$ || ! -x "$TRUSTED_PYTHON_REAL" ]]; then
  echo "BLOCKED: .venv Python does not resolve to an approved system Python path. No Live order was sent."
  exit 2
fi
PYTHON_ATTESTATION="$(/usr/bin/stat -Lc '%u %a' -- "$TRUSTED_PYTHON_REAL")" || {
  echo "BLOCKED: system Python ownership/mode cannot be attested. No Live order was sent."
  exit 2
}
read -r PYTHON_OWNER_UID PYTHON_MODE <<< "$PYTHON_ATTESTATION"
if [[ "$PYTHON_OWNER_UID" != "0" || ! "$PYTHON_MODE" =~ ^[0-7]{3,4}$ ]]; then
  echo "BLOCKED: system Python ownership/mode attestation failed. No Live order was sent."
  exit 2
fi
if (( (8#$PYTHON_MODE & 0022) != 0 )); then
  echo "BLOCKED: system Python is group/world writable. No Live order was sent."
  exit 2
fi

shopt -s nullglob
VENV_SITE_CANDIDATES=("$ROOT"/.venv/lib/python*/site-packages)
shopt -u nullglob
if [[ "${#VENV_SITE_CANDIDATES[@]}" -ne 1 || ! -d "${VENV_SITE_CANDIDATES[0]}" ]]; then
  echo "BLOCKED: expected exactly one .venv site-packages directory. No Live order was sent."
  exit 2
fi
VENV_SITE_PACKAGES="${VENV_SITE_CANDIDATES[0]}"

: "${LIVE_PILOT_INTENT_ID:?BLOCKED: LIVE_PILOT_INTENT_ID is required}"
: "${LIVE_PILOT_TICKER:?BLOCKED: LIVE_PILOT_TICKER is required}"
: "${LIVE_PILOT_SIDE:?BLOCKED: LIVE_PILOT_SIDE is required}"
: "${LIVE_PILOT_QUANTITY:?BLOCKED: LIVE_PILOT_QUANTITY is required}"
: "${LIVE_PILOT_LIMIT_PRICE:?BLOCKED: LIVE_PILOT_LIMIT_PRICE is required}"
: "${LIVE_PILOT_NOTIONAL_JPY:?BLOCKED: LIVE_PILOT_NOTIONAL_JPY is required}"
: "${LIVE_PILOT_NONCE:?BLOCKED: LIVE_PILOT_NONCE is required}"
: "${LIVE_PILOT_ACCOUNT_FINGERPRINT:?BLOCKED: LIVE_PILOT_ACCOUNT_FINGERPRINT is required}"
: "${LIVE_PILOT_EXPECTED_COMMIT_SHA:?BLOCKED: LIVE_PILOT_EXPECTED_COMMIT_SHA is required}"

ACTUAL_SHA="$(git rev-parse HEAD)"
if [[ "$ACTUAL_SHA" != "$LIVE_PILOT_EXPECTED_COMMIT_SHA" ]]; then
  echo "BLOCKED: checkout SHA does not match the explicitly approved SHA. No Live order was sent."
  exit 2
fi

# Fail closed before launching any Python from this checkout.  The in-process
# source/PIN audit is still required later, but it is too late to protect
# against import-time execution if tracked source has been edited after the
# explicitly approved commit was chosen.
SOURCE_DIRTY="$(git status --porcelain=v1 --untracked-files=all -- \
  src \
  tests \
  scripts \
  requirements.txt \
  pyproject.toml \
  pytest.ini \
  .github/workflows/pytest.yml \
  live_pilot_operational_once.sh)"
if [[ -n "$SOURCE_DIRTY" ]]; then
  echo "BLOCKED: tracked or untracked audited source changes are present before Python launch. No Live order was sent."
  exit 2
fi

# git status can intentionally suppress worktree checks for assume-unchanged
# and skip-worktree entries. Reject either index flag in audited source paths
# before any Python process can execute.
INDEX_HIDDEN="$(git ls-files -v -- \
  src \
  tests \
  scripts \
  requirements.txt \
  pyproject.toml \
  pytest.ini \
  .github/workflows/pytest.yml \
  live_pilot_operational_once.sh | \
  awk '$1 == "S" || $1 ~ /^[a-z]$/ { print }')"
if [[ -n "$INDEX_HIDDEN" ]]; then
  echo "BLOCKED: audited source contains assume-unchanged or skip-worktree index entries. No Live order was sent."
  exit 2
fi

# Git intentionally hides ignored files from status.  Most ignored runtime
# caches are harmless, but importable source/bytecode/native-extension artifacts
# under audited code paths could execute before the in-process audit.  Detect
# those explicitly while allowing normal __pycache__ entries.
IGNORED_IMPORTABLE="$(
  git ls-files --others --ignored --exclude-standard -- src tests scripts |
    while IFS= read -r path; do
      if [[ -L "$path" ]]; then
        printf '%s\n' "$path"
        continue
      fi
      case "$path" in
        */__pycache__/*)
          ;;
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
  echo "BLOCKED: ignored importable artifact, package, or symlink is present in an audited source path. No Live order was sent."
  exit 2
fi

# Do not source .venv/bin/activate or execute a mutable .venv interpreter.
# The .venv Python link is resolved above to an OS-managed, root-owned,
# non-writable /usr/bin/python3* target and that resolved path is executed.
# -I/-P/-S suppress environment, current-directory, user-site, sitecustomize,
# and .pth startup hooks. The audited checkout and venv dependency directory
# are added explicitly after isolated startup.
unset PYTHONPATH PYTHONHOME
PYTHON_BOOTSTRAP='
import runpy
import sys

repo_root = sys.argv[1]
site_packages = sys.argv[2]
operational_args = sys.argv[3:]
sys.path.insert(0, site_packages)
sys.path.insert(0, repo_root + "/src")
sys.argv = ["ai_asset_platform.execution.live_pilot_operational_entrypoint", *operational_args]
runpy.run_module(
    "ai_asset_platform.execution.live_pilot_operational_entrypoint",
    run_name="__main__",
    alter_sys=True,
)
'

"$TRUSTED_PYTHON_REAL" -I -P -S -c "$PYTHON_BOOTSTRAP" "$ROOT" "$VENV_SITE_PACKAGES" \
  --intent-id "$LIVE_PILOT_INTENT_ID" \
  --ticker "$LIVE_PILOT_TICKER" \
  --side "$LIVE_PILOT_SIDE" \
  --quantity "$LIVE_PILOT_QUANTITY" \
  --limit-price "$LIVE_PILOT_LIMIT_PRICE" \
  --estimated-notional-jpy "$LIVE_PILOT_NOTIONAL_JPY" \
  --nonce "$LIVE_PILOT_NONCE" \
  --account-fingerprint "$LIVE_PILOT_ACCOUNT_FINGERPRINT" \
  --expected-commit-sha "$LIVE_PILOT_EXPECTED_COMMIT_SHA" \
  --final-confirmation "${LIVE_PILOT_FINAL_CONFIRMATION:-}" \
  --live-readonly-confirmation "READ_LIVE_ACCOUNT_ONLY" \
  --repository-root "$ROOT"
