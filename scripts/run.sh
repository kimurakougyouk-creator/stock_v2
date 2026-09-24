#!/bin/sh
set -eu

# Supported startup path is direct execution only: ./scripts/run.sh
if [ -n "${BASH_VERSION:-}" ]; then
  echo "BLOCKED: invoke ./scripts/run.sh directly; explicit Bash invocation is unsupported." >&2
  exit 2
fi

SCRIPT_PATH="$(/usr/bin/readlink -f -- "$0")"
ROOT="${SCRIPT_PATH%/scripts/run.sh}"
exec "$ROOT/start.sh" "$@"
