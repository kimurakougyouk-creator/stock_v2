#!/usr/bin/env bash
# Shared runtime-binding gate for self-updating operational wrappers.
#
# Precondition: the caller has already `cd`'d to the repo root, run
# `source .venv/bin/activate`, and `unset PYTHONPATH`. Invoke this as a
# plain command (e.g. `bash scripts/ensure_exact_checkout_runtime.sh`)
# immediately before the first ai_asset_platform use; under the caller's
# `set -e`, a non-zero exit here aborts before that use.
#
# Design: verify first, migrate only on failure, then re-verify.
# - If ai_asset_platform already resolves to this exact checkout, this
#   never calls pip and never touches the network. Read-only wrappers that
#   must keep monitoring when origin is unreachable (e.g. ibkr_auto.sh's
#   `git pull` failure path) stay fully offline-capable as long as .venv
#   was already migrated once -- which it will be, since this same gate
#   performs that migration on first use.
# - pip is only invoked when the first verify fails (a genuinely stale or
#   never-migrated .venv). That editable install can require network (PEP
#   517 build isolation fetches the build backend from PyPI; this repo's
#   own .venv does not retain setuptools/wheel after its own initial
#   install, so `--no-build-isolation` cannot be assumed to work here). A
#   failure during migration is reported and this script exits non-zero --
#   it never silently continues with a broken or absent ai_asset_platform.
#
# Reuses scripts/verify_exact_checkout_import.py; does not duplicate its logic.
set -euo pipefail

PYTHON_BIN="${AI_ASSET_PYTHON_BIN:-python}"

if "$PYTHON_BIN" scripts/verify_exact_checkout_import.py; then
  exit 0
fi

echo "ai_asset_platform did not resolve to the current checkout; migrating this .venv (pip install -e .)." >&2
if ! "$PYTHON_BIN" -m pip install -e .; then
  echo "FATAL: editable install migration failed (network unavailable or another pip error). No order was sent." >&2
  exit 1
fi

if ! "$PYTHON_BIN" scripts/verify_exact_checkout_import.py; then
  echo "FATAL: ai_asset_platform still does not resolve to this checkout after migration. No order was sent." >&2
  exit 1
fi
