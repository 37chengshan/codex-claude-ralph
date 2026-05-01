#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
shift || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_NAME="codex-claude-ralph"

repo=""
while (($#)); do
  case "$1" in
    --repo)
      repo="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

copy_skill() {
  local target_root="$1"
  mkdir -p "$(dirname "$target_root")"
  rm -rf "$target_root"
  mkdir -p "$target_root"
  rsync -a \
    --exclude '.git/' \
    --exclude '.codex-ralph/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '.DS_Store' \
    "$SKILL_ROOT/" "$target_root/"
  chmod +x "$target_root/ralph.sh" "$target_root/runtime/ralph.sh" "$target_root/install/install.sh" "$target_root/install/doctor.sh"
  chmod +x "$target_root/runtime/scripts/"*.sh "$target_root/runtime/scripts/"*.py
  chmod +x "$target_root/runtime/orchestrator.py" "$target_root/orchestrator.py"
}

install_hook_stub() {
  local target_root="$1"
  local hook_name="$2"
  local hook_src="$3"
  mkdir -p "$target_root/.codex/hooks"
  cp "$hook_src" "$target_root/.codex/hooks/$hook_name"
}

case "$MODE" in
  global)
    target="$HOME/.codex/skills/$SKILL_NAME"
    copy_skill "$target"
    mkdir -p "$HOME/.codex/hooks"
    cp "$SKILL_ROOT/hooks/settings.global.json" "$HOME/.codex/hooks/$SKILL_NAME.settings.json"
    echo "Installed global skill to $target"
    ;;
  project)
    if [[ -z "$repo" ]]; then
      echo "project mode requires --repo <path>" >&2
      exit 2
    fi
    repo="$(cd "$repo" && pwd)"
    target="$repo/.codex/skills/$SKILL_NAME"
    copy_skill "$target"
    mkdir -p "$repo/.codex/hooks"
    cp "$SKILL_ROOT/hooks/settings.project.json" "$repo/.codex/hooks/$SKILL_NAME.settings.json"
    echo "Installed project-local skill to $target"
    ;;
  *)
    echo "Usage: install/install.sh global | project --repo <repo>" >&2
    exit 2
    ;;
esac
