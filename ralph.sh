#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SKILL_ROOT="${SKILL_ROOT:-$ROOT_DIR}"

exec "$ROOT_DIR/runtime/ralph.sh" "$@"
