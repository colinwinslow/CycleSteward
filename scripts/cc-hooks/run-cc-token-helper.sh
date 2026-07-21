#!/usr/bin/env bash
# Launcher for cc_token_usage.py — Claude Code equivalent of run-codex-token-helper.sh.
# Finds a usable Python 3.10+ and delegates to scripts/cc_token_usage.py.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
# CC_PY_SCRIPT lets sibling tools (e.g. cc_spend.py, cc_continuity.py) reuse this
# launcher's Python discovery. Defaults to the token helper for hook callers.
helper_script="${CC_PY_SCRIPT:-cc_token_usage.py}"
helper="$repo_root/scripts/$helper_script"

python_version_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

run_with_python() {
  python_version_ok "$1" || return 1
  exec "$1" "$helper" "${@:2}"
}

if [[ -n "${CC_TOKEN_USAGE_PYTHON:-}" ]]; then
  run_with_python "$CC_TOKEN_USAGE_PYTHON" "$@" || true
fi

for name in python3 python; do
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] && run_with_python "$candidate" "$@" || true
  done < <(type -aP "$name" 2>/dev/null || true)
done

echo "[cc-token-usage] ERROR: no usable Python 3.10+ runtime found" >&2
echo "[cc-token-usage] Set CC_TOKEN_USAGE_PYTHON to a Python 3.10+ binary." >&2
exit 1
