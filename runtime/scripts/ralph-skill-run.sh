#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_ROOT="$(cd "$RUNTIME_ROOT/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

repo=""
goal_spec=""
plan_score=""
max_steps="5"
allow_non_git=0
visual=0

while (($#)); do
  case "$1" in
    --repo)
      repo="${2:-}"
      shift 2
      ;;
    --goal-spec)
      goal_spec="${2:-}"
      shift 2
      ;;
    --plan-score)
      plan_score="${2:-}"
      shift 2
      ;;
    --max-steps)
      max_steps="${2:-5}"
      shift 2
      ;;
    --allow-non-git)
      allow_non_git=1
      shift
      ;;
    --visual)
      visual=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$repo" ]]; then
  repo="$PWD"
fi

if [[ -z "$goal_spec" ]]; then
  echo "Missing --goal-spec" >&2
  exit 2
fi

if [[ ! -f "$goal_spec" ]]; then
  echo "GoalSpec not found: $goal_spec" >&2
  exit 2
fi

export SKILL_ROOT
export TARGET_REPO="$repo"

init_args=(init --repo "$repo" --goal-spec "$goal_spec")
if [[ -n "$plan_score" ]]; then
  init_args+=(--plan-score "$plan_score")
fi
if [[ "$allow_non_git" -eq 1 ]]; then
  init_args+=(--allow-non-git)
fi

"$PYTHON_BIN" "$RUNTIME_ROOT/orchestrator.py" "${init_args[@]}"

run_args=(run --repo "$repo" --max-steps "$max_steps")
if [[ "$visual" -eq 1 ]]; then
  run_args+=(--visual)
fi

"$PYTHON_BIN" "$RUNTIME_ROOT/orchestrator.py" "${run_args[@]}"
"$PYTHON_BIN" "$RUNTIME_ROOT/orchestrator.py" status --repo "$repo" --json
