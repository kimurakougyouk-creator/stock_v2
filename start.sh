#!/bin/sh
set -eu

# Security contract: execute directly (./start.sh). A caller-selected Bash may
# process BASH_ENV before this file gets control, so that mode is unsupported.
if [ -n "${BASH_VERSION:-}" ]; then
  echo "BLOCKED: invoke ./start.sh directly; explicit Bash invocation is unsupported." >&2
  exit 2
fi

SCRIPT_PATH="$(/usr/bin/readlink -f -- "$0")"
SCRIPT_DIR="${SCRIPT_PATH%/*}"
exec /usr/bin/env -i \
  AI_ASSET_PLATFORM_ROOT="$SCRIPT_DIR" \
  HOME="${HOME:-}" \
  USER="${USER:-}" \
  LOGNAME="${LOGNAME:-}" \
  LANG="${LANG:-C.UTF-8}" \
  PATH="/usr/local/bin:/usr/bin:/bin" \
  PYTHONDONTWRITEBYTECODE=1 \
  /bin/bash --noprofile --norc "$SCRIPT_DIR/scripts/start_sanitized.sh" "$@"
