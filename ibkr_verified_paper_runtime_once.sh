#!/bin/sh
set -eu

# Security contract: execute this entrypoint directly (./ibkr_verified_paper_runtime_once.sh).
# An explicitly caller-chosen Bash starts before this file can sanitize that
# shell's startup environment, so that invocation mode is unsupported.
if [ -n "${BASH_VERSION:-}" ]; then
  echo "BLOCKED: invoke this operational entrypoint directly (./ibkr_verified_paper_runtime_once.sh); explicit Bash invocation is unsupported." >&2
  exit 2
fi

ROOT="${AI_ASSET_PLATFORM_ROOT:-${HOME:-}/stock_v2_latest}"

exec /usr/bin/env -i \
  HOME="${HOME:-}" \
  USER="${USER:-}" \
  LOGNAME="${LOGNAME:-}" \
  LANG="${LANG:-C.UTF-8}" \
  PATH="/usr/local/bin:/usr/bin:/bin" \
  PYTHONDONTWRITEBYTECODE=1 \
  AI_ASSET_PLATFORM_ROOT="$ROOT" \
  /bin/bash --noprofile --norc "$ROOT/scripts/ibkr_verified_paper_runtime_once_sanitized.sh" "$@"
