#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
INTERVAL_SECONDS="${IBKR_AUTOPILOT_INTERVAL_SECONDS:-300}"
MAX_LOG_BYTES="${IBKR_AUTOPILOT_MAX_LOG_BYTES:-5242880}"
PIN_FILE="${IBKR_AUTOPILOT_PIN_FILE:-$HOME/.config/ai-asset-platform/ibkr-readonly-autopilot-pinned-head}"
LOG_DIR="$REPO_DIR/results"
LOG_FILE="$LOG_DIR/ibkr_readonly_autopilot.log"
ROTATED_LOG_FILE="$LOG_FILE.1"
MONITOR_LOG="$LOG_DIR/ibkr_paper_operations_monitor_latest.log"
TRUSTED_PYTHON="/usr/bin/python3"
ISOLATED_RUNNER="$REPO_DIR/scripts/run_isolated_venv_python.py"
STRICT_MONITOR_MODULE="ai_asset_platform.brokers.ibkr_paper_operations_monitor_strict"

# Python is always launched with -I -S through the attested runner below.
# Clear inherited Python path/home hints anyway so non-Python helper commands
# cannot accidentally propagate them to a future child process.
unset PYTHONPATH PYTHONHOME

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
    elif [[ -x .venv/bin/python && -f "$ISOLATED_RUNNER" && -x "$TRUSTED_PYTHON" ]]; then
      set +e
      # Strict unattended policy: execute only the read-only Paper monitor
      # through the already-audited isolated bootstrap. The bootstrap attests
      # the current source, verifies the venv dependency bytes, blocks startup
      # hooks/cwd shadowing with -I -S, and (via the explicit flag below)
      # verifies the pinned ibapi manifest before importing broker modules.
      #
      # Existing monitor environment variables remain inherited unchanged;
      # Python-specific path/home injection is ignored by -I and cleared above.
      AI_ASSET_PLATFORM_ROOT="$REPO_DIR" \
      AI_ASSET_REQUIRE_PINNED_IBAPI=1 \
        "$TRUSTED_PYTHON" -I -S "$ISOLATED_RUNNER" \
          -m "$STRICT_MONITOR_MODULE" \
          2>&1 | tee "$MONITOR_LOG"
      monitor_status=${PIPESTATUS[0]}
      set -e
      if [[ "$monitor_status" -eq 2 ]]; then
        echo "PAPER OPERATIONS CRITICAL: manual review is required; no order was changed, cancelled, or retried."
      elif [[ "$monitor_status" -eq 1 ]]; then
        echo "PAPER OPERATIONS WARNING: monitoring continues; no order was changed, cancelled, or retried."
      fi
      echo "PAPER OPERATIONS MONITOR LOG: $MONITOR_LOG"
    else
      echo "AUTOPILOT SOURCE BLOCKED: trusted Python, isolated runner, or .venv Python is unavailable. Monitoring code was not executed."
    fi
    echo "PINNED AUDITED HEAD: $PINNED_HEAD"
    echo "ORDER API REQUEST SENT: False"
    echo "REAL ORDER SENT: False"
    echo "LIVE ORDER SENT: False"
  } >>"$LOG_FILE" 2>&1 || true
  sleep "$INTERVAL_SECONDS"
done
