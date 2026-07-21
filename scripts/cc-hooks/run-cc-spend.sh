#!/usr/bin/env bash
# Launcher for the Claude Code spend gauge (scripts/cc_spend.py). Reuses the token
# helper's Python discovery via CC_PY_SCRIPT so the gauge runs the same way
# everywhere.
#
#   bash scripts/cc-hooks/run-cc-spend.sh dashboard --packet "..."
#   bash scripts/cc-hooks/run-cc-spend.sh gauge --tier thin
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
exec env CC_PY_SCRIPT=cc_spend.py \
  bash "$repo_root/scripts/cc-hooks/run-cc-token-helper.sh" "$@"
