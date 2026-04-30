#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cmd="run"
tool="claude"
args=()
has_repo_arg=0
has_init_input=0
repo_args=()

while (($#)); do
  case "$1" in
    init|run|status|doctor)
      cmd="$1"
      shift
      ;;
    --tool)
      tool="${2:-}"
      shift 2
      ;;
    --tool=*)
      tool="${1#*=}"
      shift
      ;;
    --repo|--repo=*)
      has_repo_arg=1
      if [[ "$1" == "--repo" ]]; then
        repo_args=(--repo "${2:-}")
        shift 2
      else
        repo_args=("$1")
        shift
      fi
      ;;
    --goal|--goal=*|--prd-file|--prd-file=*|--import-prd-json|--import-prd-json=*)
      has_init_input=1
      args+=("$1")
      if [[ "$1" == "--goal" || "$1" == "--prd-file" || "$1" == "--import-prd-json" ]]; then
        args+=("${2:-}")
        shift 2
      else
        shift
      fi
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

case "$tool" in
  ""|claude)
    ;;
  amp)
    echo "Amp is not supported in this Codex-only Ralph fork. Use --tool claude." >&2
    exit 2
    ;;
  *)
    echo "Unsupported tool: $tool. Only --tool claude is supported." >&2
    exit 2
    ;;
esac

if [[ "$cmd" == "init" && $has_init_input -eq 0 ]]; then
  if [[ ! -f "$ROOT_DIR/prompt.md" ]]; then
    echo "No init input supplied and prompt.md is missing." >&2
    exit 1
  fi
  if [[ ${#args[@]} -gt 0 ]]; then
    args=(--prd-file "$ROOT_DIR/prompt.md" "${args[@]}")
  else
    args=(--prd-file "$ROOT_DIR/prompt.md")
  fi
fi

if [[ "$cmd" == "run" && ! -f "$ROOT_DIR/prd.json" && -f "$ROOT_DIR/prompt.md" ]]; then
  if [[ $has_repo_arg -eq 0 ]]; then
    repo_args=(--repo "$ROOT_DIR")
  fi
  "$PYTHON_BIN" "$ROOT_DIR/orchestrator.py" init "${repo_args[@]}" --prd-file "$ROOT_DIR/prompt.md"
fi

if [[ "$cmd" == "init" && $has_repo_arg -eq 0 ]]; then
  repo_args=(--repo "$ROOT_DIR")
fi

if [[ "$cmd" == "init" ]]; then
  if [[ ${#args[@]} -gt 0 ]]; then
    exec "$PYTHON_BIN" "$ROOT_DIR/orchestrator.py" "$cmd" "${repo_args[@]}" "${args[@]}"
  else
    exec "$PYTHON_BIN" "$ROOT_DIR/orchestrator.py" "$cmd" "${repo_args[@]}"
  fi
fi

if [[ ${#args[@]} -gt 0 ]]; then
  exec "$PYTHON_BIN" "$ROOT_DIR/orchestrator.py" "$cmd" "${args[@]}"
else
  exec "$PYTHON_BIN" "$ROOT_DIR/orchestrator.py" "$cmd"
fi
