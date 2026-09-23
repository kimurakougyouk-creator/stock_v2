#!/usr/bin/env bash
set -Eeuo pipefail

# Every external invocation crosses a clean exec boundary. There is no
# caller-supplied "already sanitized" marker that can bypass this step.
unset BASH_ENV ENV CDPATH PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH
unset -f git awk bash python pytest env 2>/dev/null || true
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
