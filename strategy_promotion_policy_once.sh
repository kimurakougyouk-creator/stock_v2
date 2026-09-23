#!/bin/sh
set -eu

ROOT="${AI_ASSET_PLATFORM_ROOT:-${HOME:-}/stock_v2_latest}"

exec /usr/bin/env -i \
  HOME="${HOME:-}" \
  USER="${USER:-}" \
  LOGNAME="${LOGNAME:-}" \
  LANG="${LANG:-C.UTF-8}" \
  PATH="/usr/local/bin:/usr/bin:/bin" \
  PYTHONDONTWRITEBYTECODE=1 \
  AI_ASSET_PLATFORM_ROOT="$ROOT" \
  /bin/bash --noprofile --norc "$ROOT/scripts/strategy_promotion_policy_once_sanitized.sh" "$@"
