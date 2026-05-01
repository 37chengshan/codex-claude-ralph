#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

export SKILL_ROOT

cmd="${1:-run}"
if (($#)); then
  shift
fi

case "$cmd" in
  -h|--help)
    set -- "$cmd" "$@"
    cmd=""
    ;;
  init|run|status|answer|doctor|plan|launch|collect|review-mark|merge|handoff|playwright)
    ;;
  *)
    set -- "$cmd" "$@"
    cmd="run"
    ;;
esac

if [[ -n "$cmd" ]]; then
  exec "$PYTHON_BIN" "$SCRIPT_DIR/orchestrator.py" "$cmd" "$@"
fi
exec "$PYTHON_BIN" "$SCRIPT_DIR/orchestrator.py" "$@"
