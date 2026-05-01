#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
repo=""
json=0

while (($#)); do
  case "$1" in
    --repo)
      repo="${2:-}"
      shift 2
      ;;
    --json)
      json=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

export SKILL_ROOT

args=(doctor)
if [[ -n "$repo" ]]; then
  args+=(--repo "$repo")
fi
if [[ "$json" -eq 1 ]]; then
  args+=(--json)
fi

exec "$PYTHON_BIN" "$SKILL_ROOT/runtime/orchestrator.py" "${args[@]}"
