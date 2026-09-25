#!/bin/sh
# The installed systemd unit is the trusted unattended entrypoint. It removes
# dynamic-loader/shell/Python startup overrides before /bin/sh is created.
# A direct manual launch cannot undo LD_PRELOAD/LD_LIBRARY_PATH after the
# dynamic loader has already started this shell, so refuse that unsupported
# case before any repository command or monitor code runs.
if [ -n "${LD_PRELOAD:-}" ] || [ -n "${LD_LIBRARY_PATH:-}" ]; then
  echo "BLOCKED: direct launch with LD_PRELOAD/LD_LIBRARY_PATH is unsupported. Use the installed systemd service. No order was sent." >&2
  exit 2
fi

# For normal direct launches, clear shell/Python startup controls and rebuild
# a minimal environment before Bash can evaluate BASH_ENV, inherited functions,
# a hostile PATH, or Python startup-path variables.
if [ -z "${BASH_VERSION:-}" ] || ! (set -o pipefail) 2>/dev/null; then
  if [ -z "${HOME:-}" ]; then
    echo "BLOCKED: HOME is unavailable. No order was sent." >&2
    exit 2
  fi
  SCRIPT_PATH="$0"
  unset BASH_ENV ENV CDPATH PYTHONPATH PYTHONHOME PYTHONSTARTUP
  exec /usr/bin/env -i \
    HOME="$HOME" \
    USER="${USER:-}" \
    LOGNAME="${LOGNAME:-}" \
    LANG="${LANG:-C.UTF-8}" \
    PATH=/usr/local/bin:/usr/bin:/bin \
    IBKR_REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}" \
    IBKR_AUTOPILOT_INTERVAL_SECONDS="${IBKR_AUTOPILOT_INTERVAL_SECONDS:-300}" \
    IBKR_AUTOPILOT_MAX_LOG_BYTES="${IBKR_AUTOPILOT_MAX_LOG_BYTES:-5242880}" \
    IBKR_AUTOPILOT_PIN_FILE="${IBKR_AUTOPILOT_PIN_FILE:-$HOME/.config/ai-asset-platform/ibkr-readonly-autopilot-pinned-head}" \
    IBKR_AUTOPILOT_PINNED_HEAD="${IBKR_AUTOPILOT_PINNED_HEAD:-}" \
    IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS="${IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS:-96}" \
    IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES="${IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES:-10485760}" \
    IBKR_PAPER_MONITOR_EMAIL_ALERTS="${IBKR_PAPER_MONITOR_EMAIL_ALERTS:-auto}" \
    IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS="${IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS:-12}" \
    /bin/bash --noprofile --norc "$SCRIPT_PATH" "$@"
fi

set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
INTERVAL_SECONDS="${IBKR_AUTOPILOT_INTERVAL_SECONDS:-300}"
MAX_LOG_BYTES="${IBKR_AUTOPILOT_MAX_LOG_BYTES:-5242880}"
PIN_FILE="${IBKR_AUTOPILOT_PIN_FILE:-$HOME/.config/ai-asset-platform/ibkr-readonly-autopilot-pinned-head}"
LOG_DIR="$REPO_DIR/results"
LOG_FILE="$LOG_DIR/ibkr_readonly_autopilot.log"
ROTATED_LOG_FILE="$LOG_FILE.1"
MONITOR_LOG="$LOG_DIR/ibkr_paper_operations_monitor_latest.log"

cd "$REPO_DIR"
mkdir -p "$LOG_DIR"

if ! [[ "$INTERVAL_SECONDS" =~ ^[0-9]+$ ]] || (( INTERVAL_SECONDS < 30 || INTERVAL_SECONDS > 86400 )); then
  echo "BLOCKED: IBKR_AUTOPILOT_INTERVAL_SECONDS must be an integer from 30 to 86400. No order was sent." >&2
  exit 2
fi
if ! [[ "$MAX_LOG_BYTES" =~ ^[0-9]+$ ]] || (( MAX_LOG_BYTES < 1048576 || MAX_LOG_BYTES > 104857600 )); then
  echo "BLOCKED: IBKR_AUTOPILOT_MAX_LOG_BYTES must be an integer from 1048576 to 104857600. No order was sent." >&2
  exit 2
fi

initial_branch="$(git branch --show-current 2>/dev/null || true)"
initial_head="$(git rev-parse HEAD 2>/dev/null || true)"
if [[ "$initial_branch" != "main" ]] || ! [[ "$initial_head" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED: unattended monitor must start from a valid local main commit. No order was sent." >&2
  exit 2
fi

# Migration path for installations created before revision pinning existed.
# The previously audited daemon may fast-forward to this audited revision once;
# this first launch freezes that exact HEAD in a local mode-0600 file. From then
# on the unattended process never fetches, pulls, switches branches, or executes
# newly downloaded code. Future upgrades require the tested installer.
if [[ -n "${IBKR_AUTOPILOT_PINNED_HEAD:-}" ]]; then
  PINNED_HEAD="$IBKR_AUTOPILOT_PINNED_HEAD"
elif [[ -f "$PIN_FILE" ]]; then
  PINNED_HEAD="$(tr -d '[:space:]' < "$PIN_FILE")"
else
  PINNED_HEAD="$initial_head"
  mkdir -p "$(dirname "$PIN_FILE")"
  pin_tmp="$PIN_FILE.tmp"
  umask 077
  printf '%s\n' "$PINNED_HEAD" > "$pin_tmp"
  chmod 600 "$pin_tmp"
  mv -f "$pin_tmp" "$PIN_FILE"
  echo "AUTOPILOT MIGRATION PIN: $PINNED_HEAD"
fi
if ! [[ "$PINNED_HEAD" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED: unattended monitor pinned revision is invalid. No order was sent." >&2
  exit 2
fi

rotate_autopilot_log_if_needed() {
  local current_size=0
  if [[ -f "$LOG_FILE" ]]; then
    current_size="$(wc -c < "$LOG_FILE" 2>/dev/null || printf '0')"
  fi
  if [[ "$current_size" =~ ^[0-9]+$ ]] && (( current_size >= MAX_LOG_BYTES )); then
    mv -f "$LOG_FILE" "$ROTATED_LOG_FILE"
  fi
}

tracked_source_is_clean() {
  git diff --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**' && \
    git diff --cached --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**'
}

while true; do
  rotate_autopilot_log_if_needed
  {
    echo "===== $(date -Is) IBKR READ-ONLY AUTOPILOT ====="
    current_branch="$(git branch --show-current 2>/dev/null || true)"
    current_head="$(git rev-parse HEAD 2>/dev/null || true)"

    # Never mutate or update source code from an unattended trading-safety
    # service. Only the exact commit approved by the installer/bootstrap pin may
    # execute. Runtime artifacts under results/ and data/ are intentionally
    # excluded from the tracked-source cleanliness check.
    if [[ "$current_branch" != "main" ]]; then
      echo "AUTOPILOT SOURCE BLOCKED: local branch is '$current_branch', expected 'main'. Monitoring code was not executed."
    elif [[ "$current_head" != "$PINNED_HEAD" ]]; then
      echo "AUTOPILOT SOURCE BLOCKED: local HEAD $current_head differs from pinned audited HEAD $PINNED_HEAD. Rerun the tested installer after review."
    elif ! tracked_source_is_clean; then
      echo "AUTOPILOT SOURCE BLOCKED: tracked source differs from pinned HEAD outside runtime output directories. Monitoring code was not executed."
    elif [[ -x .venv/bin/python ]]; then
      # Keep this 300-second unattended path lightweight. Do not copy/hash the
      # entire venv every cycle. Instead:
      # 1. prove the venv interpreter is the trusted /usr/bin/python3;
      # 2. prove tracked/untracked importable repository source is clean;
      # 3. verify the exact pinned ibapi package only;
      # 4. launch with -I -P -S and append dependency/application paths only
      #    after the standard library, without processing .pth/sitecustomize.
      TRUSTED_PYTHON_REAL="$(/usr/bin/readlink -f -- /usr/bin/python3 2>/dev/null || true)"
      VENV_PYTHON_REAL="$(/usr/bin/readlink -f -- .venv/bin/python 2>/dev/null || true)"
      if [[ -z "$TRUSTED_PYTHON_REAL" || "$VENV_PYTHON_REAL" != "$TRUSTED_PYTHON_REAL" ]]; then
        echo "AUTOPILOT SOURCE BLOCKED: .venv interpreter does not match trusted /usr/bin/python3. Monitoring code was not executed."
      elif ! /bin/bash --noprofile --norc scripts/verify_strategy_source_clean.sh >/dev/null; then
        echo "AUTOPILOT SOURCE BLOCKED: source/startup-path attestation failed this cycle. Monitoring code was not executed."
      else
        PY_MINOR="$(/usr/bin/python3 -I -P -S -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')"
        VENV_SITE_PACKAGES=""
        for candidate in \
          "$REPO_DIR/.venv/lib/$PY_MINOR/site-packages" \
          "$REPO_DIR/.venv/lib64/$PY_MINOR/site-packages"
        do
          if [[ -d "$candidate" ]]; then
            if [[ -n "$VENV_SITE_PACKAGES" ]]; then
              VENV_SITE_PACKAGES="AMBIGUOUS"
              break
            fi
            VENV_SITE_PACKAGES="$candidate"
          fi
        done

        if [[ -z "$VENV_SITE_PACKAGES" || "$VENV_SITE_PACKAGES" == "AMBIGUOUS" ]]; then
          echo "AUTOPILOT SOURCE BLOCKED: exactly one interpreter-matching venv site-packages directory is required. Monitoring code was not executed."
        elif ! /usr/bin/python3 -I -P -S "$REPO_DIR/scripts/verify_live_ibapi_runtime.py" \
          --site-packages "$VENV_SITE_PACKAGES" \
          --manifest "$REPO_DIR/scripts/live_ibapi_manifest.json" >/dev/null
        then
          echo "AUTOPILOT SOURCE BLOCKED: pinned ibapi verification failed this cycle. Monitoring code was not executed."
        else
          set +e
          /usr/bin/python3 -I -P -S - "$REPO_DIR" "$VENV_SITE_PACKAGES" \
            2>&1 <<'PY' | tee "$MONITOR_LOG"
from __future__ import annotations

import importlib.util
from pathlib import Path
import runpy
import sys

root = Path(sys.argv[1]).resolve()
site_packages = Path(sys.argv[2]).resolve()
src = (root / "src").resolve()

if not root.is_dir() or not src.is_dir() or not site_packages.is_dir():
    raise SystemExit("BLOCKED: Paper monitor runtime paths are unavailable")

# -I -P -S leaves cwd/repository/site-packages out of startup sys.path.
# Add dependencies first, then application source/legacy root, all after the
# already-established stdlib entries. This prevents repository files from
# shadowing stdlib or installed third-party packages. Because site is disabled,
# adding site-packages directly does not process .pth files or sitecustomize.
for entry in tuple(sys.path):
    if not entry:
        raise SystemExit("BLOCKED: unsafe empty startup sys.path entry")
    try:
        resolved = Path(entry).resolve()
    except OSError:
        continue
    if resolved in {root, src, site_packages}:
        raise SystemExit(
            "BLOCKED: repository/dependency path entered sys.path before bootstrap"
        )

sys.path.extend([str(site_packages), str(src), str(root)])


def _origin(name: str) -> Path:
    spec = importlib.util.find_spec(name)
    if spec is None or spec.origin in {None, "built-in", "frozen"}:
        raise SystemExit(f"BLOCKED: import origin is unavailable for {name}")
    return Path(spec.origin).resolve()


expected_package = (src / "ai_asset_platform" / "__init__.py").resolve()
if _origin("ai_asset_platform") != expected_package:
    raise SystemExit(
        "BLOCKED: ai_asset_platform does not resolve to the audited checkout"
    )

# These legacy root modules are reached transitively by the strict monitor.
# Fail closed if an installed dependency shadows any of them.
for module_name in ("config", "paper_trading_runner", "signal_runner"):
    expected = (root / f"{module_name}.py").resolve()
    if _origin(module_name) != expected:
        raise SystemExit(
            f"BLOCKED: legacy runtime module {module_name} is shadowed"
        )

# Re-check representative stdlib modules involved in the original Issue #285
# shadow demonstrations after all paths are appended.
for protected in ("keyword", "dataclasses", "json"):
    spec = importlib.util.find_spec(protected)
    if spec is None:
        raise SystemExit(
            f"BLOCKED: protected stdlib module {protected} is unavailable"
        )
    if spec.origin not in {None, "built-in", "frozen"}:
        resolved = Path(spec.origin).resolve()
        if (
            resolved == root
            or root in resolved.parents
            or resolved == site_packages
            or site_packages in resolved.parents
        ):
            raise SystemExit(
                f"BLOCKED: protected stdlib module {protected} is shadowed"
            )

runpy.run_module(
    "ai_asset_platform.brokers.ibkr_paper_operations_monitor_strict",
    run_name="__main__",
    alter_sys=True,
)
PY
          monitor_status=${PIPESTATUS[0]}
          set -e
          if [[ "$monitor_status" -eq 2 ]]; then
            echo "PAPER OPERATIONS CRITICAL: manual review is required; no order was changed, cancelled, or retried."
          elif [[ "$monitor_status" -eq 1 ]]; then
            echo "PAPER OPERATIONS WARNING: monitoring continues; no order was changed, cancelled, or retried."
          fi
          echo "PAPER OPERATIONS MONITOR LOG: $MONITOR_LOG"
        fi
      fi
    else
      echo "SKIP: .venv/bin/python not found. No order was sent."
    fi
    echo "PINNED AUDITED HEAD: $PINNED_HEAD"
    echo "ORDER API REQUEST SENT: False"
    echo "REAL ORDER SENT: False"
    echo "LIVE ORDER SENT: False"
  } >>"$LOG_FILE" 2>&1 || true
  sleep "$INTERVAL_SECONDS"
done
