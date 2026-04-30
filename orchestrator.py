#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PUBLIC_PRD_PATH = ROOT / "prd.json"
PUBLIC_PROGRESS_PATH = ROOT / "progress.txt"
PUBLIC_PROMPT_PATH = ROOT / "prompt.md"
PUBLIC_CLAUDE_PATH = ROOT / "CLAUDE.md"
PUBLIC_PRD_EXAMPLE_PATH = ROOT / "prd.json.example"
HIDDEN_DIR = ROOT / ".codex-ralph"
INTERNAL_CONFIG_PATH = HIDDEN_DIR / "config.json"
INTERNAL_STATE_PATH = HIDDEN_DIR / "state.json"
INTERNAL_RUNS_DIR = HIDDEN_DIR / "runs"
INTERNAL_ARCHIVE_DIR = HIDDEN_DIR / "archive"
LOCK_PATH = HIDDEN_DIR / ".run.lock"
SCHEMAS_DIR = ROOT / "schemas"
LEGACY_STATE_DIR = ROOT / "state"
BROWSER_VERIFY_SCRIPT = ROOT / "browser_verify.py"

STATUS_VALUES = {"pending", "running", "passed", "blocked", "failed"}
UI_KEYWORDS = ("ui", "browser", "frontend", "page", "screen", "component", "css", "react")


class OrchestratorError(RuntimeError):
    """Base error for user-facing orchestration failures."""


class PlanValidationError(OrchestratorError):
    """Raised when public or internal state is malformed."""


class ToolInvocationError(OrchestratorError):
    """Raised when planner/worker/reviewer commands fail or return bad payloads."""

    def __init__(
        self,
        phase: str,
        message: str,
        *,
        retryable: bool = False,
        details: str | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.retryable = retryable
        self.details = details or message


@dataclass
class CommandResult:
    args: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "args": self.args,
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_hidden_dirs() -> None:
    HIDDEN_DIR.mkdir(parents=True, exist_ok=True)
    INTERNAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    INTERNAL_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_lock_info() -> dict[str, Any] | None:
    if not LOCK_PATH.exists():
        return None
    raw = LOCK_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return {"pid": None, "timestamp": None, "raw": raw}
    parts = raw.split(maxsplit=1)
    pid: int | None = None
    try:
        pid = int(parts[0])
    except (TypeError, ValueError):
        pid = None
    timestamp = parts[1] if len(parts) > 1 else None
    return {"pid": pid, "timestamp": timestamp, "raw": raw}


def is_pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_is_active() -> bool:
    info = read_lock_info()
    return bool(info and is_pid_alive(info.get("pid")))


def clear_stale_lock_if_needed() -> bool:
    if not LOCK_PATH.exists():
        return False
    if lock_is_active():
        return False
    LOCK_PATH.unlink(missing_ok=True)
    return True


def format_exception_context(result: CommandResult) -> str:
    chunks = [
        f"cwd: {result.cwd}",
        f"args: {shlex.join(result.args)}",
        f"exit: {result.returncode}",
    ]
    if result.stdout.strip():
        chunks.append("stdout:")
        chunks.append(result.stdout.strip())
    if result.stderr.strip():
        chunks.append("stderr:")
        chunks.append(result.stderr.strip())
    return "\n".join(chunks)


def run_command(
    args: list[str],
    cwd: Path,
    *,
    stdin_text: str | None = None,
    check: bool = True,
    timeout_seconds: int | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            input=stdin_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolInvocationError(
            "command",
            f"Timed out after {timeout_seconds}s: {shlex.join(args)}",
            retryable=True,
            details=str(exc),
        ) from exc
    except OSError as exc:
        raise ToolInvocationError(
            "command",
            f"Failed to launch command: {shlex.join(args)}",
            retryable=False,
            details=str(exc),
        ) from exc

    result = CommandResult(
        args=args,
        cwd=str(cwd),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if check and result.returncode != 0:
        raise OrchestratorError("Command failed.\n" + format_exception_context(result))
    return result


def slugify_branch(name: str | None) -> str:
    if not name:
        return "no-branch"
    cleaned = []
    for char in name:
        if char.isalnum() or char in {"-", "_"}:
            cleaned.append(char)
        elif char in {"/", " ", "."}:
            cleaned.append("-")
    return "".join(cleaned).strip("-") or "no-branch"


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rstrip()
    return clipped + f"\n...[truncated {len(text) - len(clipped)} chars]"


def tail_lines(text: str, limit: int) -> list[str]:
    if limit <= 0:
        return []
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-limit:]


def resolve_tool(name: str) -> str | None:
    return shutil.which(name)


def schema_type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, int):
        return "integer"
    return type(value).__name__


def validate_schema_value(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            raise ToolInvocationError("schema", f"{path} expected object, got {schema_type_name(value)}")
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise ToolInvocationError("schema", f"{path} missing required field `{key}`")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise ToolInvocationError("schema", f"{path} has unsupported fields: {', '.join(extra)}")
        for key, child_schema in properties.items():
            if key in value:
                validate_schema_value(value[key], child_schema, f"{path}.{key}")
        return

    if expected_type == "array":
        if not isinstance(value, list):
            raise ToolInvocationError("schema", f"{path} expected array, got {schema_type_name(value)}")
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            raise ToolInvocationError("schema", f"{path} expected at least {min_items} items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_schema_value(item, item_schema, f"{path}[{index}]")
        return

    if expected_type == "string" and not isinstance(value, str):
        raise ToolInvocationError("schema", f"{path} expected string, got {schema_type_name(value)}")
    if expected_type == "boolean" and not isinstance(value, bool):
        raise ToolInvocationError("schema", f"{path} expected boolean, got {schema_type_name(value)}")
    if expected_type == "integer" and not (isinstance(value, int) and not isinstance(value, bool)):
        raise ToolInvocationError("schema", f"{path} expected integer, got {schema_type_name(value)}")

    enum_values = schema.get("enum")
    if enum_values is not None and value not in enum_values:
        allowed = ", ".join(repr(item) for item in enum_values)
        raise ToolInvocationError("schema", f"{path} expected one of {allowed}, got {value!r}")


def validate_payload_against_schema(payload: Any, schema_path: Path) -> None:
    validate_schema_value(payload, read_json(schema_path))


def repo_snapshot(repo_path: Path) -> dict[str, Any]:
    inside = run_command(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_path, check=False)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        git_error = inside.stderr.strip() or inside.stdout.strip() or "Not a git repository"
        return {
            "repo_mode": "non_git",
            "head_ref": None,
            "status_short": "",
            "diff_stat": "",
            "changed_files": [],
            "git_error": git_error,
        }

    head = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, check=False)
    status = run_command(["git", "status", "--short"], cwd=repo_path, check=False)
    diff = run_command(["git", "diff", "--stat"], cwd=repo_path, check=False)
    staged_diff = run_command(["git", "diff", "--cached", "--stat"], cwd=repo_path, check=False)
    changed_files = []
    for line in status.stdout.splitlines():
        entry = line[3:].strip() if len(line) > 3 else line.strip()
        if entry and entry not in changed_files:
            changed_files.append(entry)

    diff_parts = [piece.strip() for piece in [diff.stdout, staged_diff.stdout] if piece.strip()]
    return {
        "repo_mode": "git",
        "head_ref": head.stdout.strip() or None,
        "status_short": status.stdout.strip(),
        "diff_stat": "\n".join(diff_parts).strip(),
        "changed_files": changed_files,
        "git_error": None,
    }


def compact_repo_snapshot(snapshot: dict[str, Any], max_diff_lines: int) -> dict[str, Any]:
    diff_lines = snapshot.get("diff_stat", "").splitlines()
    return {
        "repo_mode": snapshot.get("repo_mode"),
        "head_ref": snapshot.get("head_ref"),
        "status_short": snapshot.get("status_short"),
        "changed_files": snapshot.get("changed_files", []),
        "git_error": snapshot.get("git_error"),
        "diff_stat": "\n".join(diff_lines[:max_diff_lines]),
    }


def story_is_complete(story: dict[str, Any]) -> bool:
    status = story.get("status")
    if status:
        return status == "passed"
    return bool(story.get("passes") or story.get("done"))


def infer_verification_hints(story: dict[str, Any]) -> list[str]:
    haystack = " ".join(
        [
            str(story.get("title", "")),
            str(story.get("objective", "")),
            " ".join(story.get("acceptance_criteria", [])),
        ]
    ).lower()
    hints: list[str] = []
    if any(keyword in haystack for keyword in UI_KEYWORDS):
        hints.append("browser")
    return hints


def derive_suggested_tests(raw_story: dict[str, Any], acceptance_criteria: list[str]) -> list[str]:
    explicit = raw_story.get("suggested_tests") or raw_story.get("suggestedTests")
    if explicit:
        return [str(item).strip() for item in explicit if str(item).strip()]

    derived: list[str] = []
    for item in acceptance_criteria:
        lowered = item.lower()
        if "typecheck" in lowered:
            derived.append("typecheck command required")
        elif "test" in lowered:
            derived.append(item)
    if not derived:
        derived.append("manual verification required")
    return derived


def normalize_story(raw_story: dict[str, Any], index: int) -> dict[str, Any]:
    story_id = str(raw_story.get("id") or raw_story.get("storyId") or f"S{index + 1}").strip()
    title = str(raw_story.get("title") or raw_story.get("story") or raw_story.get("name") or story_id).strip()
    objective = str(raw_story.get("objective") or raw_story.get("description") or title).strip()
    acceptance = raw_story.get("acceptance_criteria") or raw_story.get("acceptanceCriteria") or []
    acceptance_criteria = [str(item).strip() for item in acceptance if str(item).strip()]
    dependencies = [str(item).strip() for item in raw_story.get("dependencies", []) if str(item).strip()]
    suggested_tests = derive_suggested_tests(raw_story, acceptance_criteria)

    if "status" in raw_story:
        status = str(raw_story["status"]).strip()
    elif raw_story.get("passes") or raw_story.get("done"):
        status = "passed"
    else:
        status = "pending"
    if status not in STATUS_VALUES:
        raise PlanValidationError(f"Story `{story_id}` has unsupported status `{status}`")

    verification_hints = [str(item).strip() for item in raw_story.get("verification_hints", []) if str(item).strip()]
    if not verification_hints:
        verification_hints = infer_verification_hints(
            {
                "title": title,
                "objective": objective,
                "acceptance_criteria": acceptance_criteria,
            }
        )

    story = {
        "id": story_id,
        "title": title,
        "objective": objective,
        "acceptance_criteria": acceptance_criteria,
        "dependencies": dependencies,
        "suggested_tests": suggested_tests,
        "status": status,
        "attempt_count": int(raw_story.get("attempt_count", 0)),
        "last_run_id": raw_story.get("last_run_id"),
        "remaining_work": [str(item).strip() for item in raw_story.get("remaining_work", []) if str(item).strip()],
        "last_review_reason": str(raw_story.get("last_review_reason", "")).strip(),
        "verification_hints": verification_hints,
    }
    if raw_story.get("notes"):
        story["notes"] = str(raw_story["notes"])
    return story


def normalize_plan(
    raw_plan: dict[str, Any],
    *,
    default_project_name: str,
    default_require_git: bool,
    source_format_override: str | None = None,
    branch_name_override: str | None = None,
) -> dict[str, Any]:
    if not isinstance(raw_plan, dict):
        raise PlanValidationError("Plan payload must be an object")

    raw_stories = raw_plan.get("stories")
    if raw_stories is None:
        raw_stories = raw_plan.get("userStories")
    if not isinstance(raw_stories, list) or not raw_stories:
        raise PlanValidationError("Plan must contain a non-empty `stories` or `userStories` array")

    stories = [normalize_story(story, index) for index, story in enumerate(raw_stories)]
    source_format = source_format_override or ("ralph_json" if "userStories" in raw_plan else raw_plan.get("source_format", "canonical_v1"))
    plan = {
        "project_name": str(raw_plan.get("project_name") or raw_plan.get("projectName") or default_project_name).strip(),
        "branch_name": branch_name_override if branch_name_override is not None else raw_plan.get("branch_name") or raw_plan.get("branchName"),
        "source_format": source_format,
        "require_git": bool(raw_plan.get("require_git", default_require_git)),
        "stories": stories,
    }
    validate_plan(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> None:
    stories = plan.get("stories")
    if not isinstance(stories, list) or not stories:
        raise PlanValidationError("Canonical plan must contain a non-empty `stories` array")

    ids = [story.get("id") for story in stories]
    if any(not story_id for story_id in ids):
        raise PlanValidationError("Every story must have a non-empty `id`")
    duplicates = sorted({story_id for story_id in ids if ids.count(story_id) > 1})
    if duplicates:
        raise PlanValidationError(f"Duplicate story IDs: {', '.join(duplicates)}")

    story_map = {story["id"]: story for story in stories}
    for story in stories:
        if not story.get("objective"):
            raise PlanValidationError(f"Story `{story['id']}` must have an objective")
        acceptance = story.get("acceptance_criteria")
        if not isinstance(acceptance, list) or not acceptance:
            raise PlanValidationError(f"Story `{story['id']}` must have acceptance criteria")
        tests = story.get("suggested_tests")
        if not isinstance(tests, list) or not tests:
            raise PlanValidationError(f"Story `{story['id']}` must have suggested tests")
        status = story.get("status")
        if status not in STATUS_VALUES:
            raise PlanValidationError(f"Story `{story['id']}` has unsupported status `{status}`")
        for dependency in story.get("dependencies", []):
            if dependency not in story_map:
                raise PlanValidationError(f"Story `{story['id']}` references missing dependency `{dependency}`")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(story_id: str) -> None:
        if story_id in visited:
            return
        if story_id in visiting:
            raise PlanValidationError(f"Cycle detected at story `{story_id}`")
        visiting.add(story_id)
        for dependency in story_map[story_id].get("dependencies", []):
            visit(dependency)
        visiting.remove(story_id)
        visited.add(story_id)

    for story_id in story_map:
        visit(story_id)


def export_public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "projectName": plan["project_name"],
        "branchName": plan.get("branch_name"),
        "userStories": [
            {
                "id": story["id"],
                "title": story["title"],
                "description": story["objective"],
                "acceptance_criteria": story["acceptance_criteria"],
                "dependencies": story["dependencies"],
                "suggested_tests": story["suggested_tests"],
                "passes": story_is_complete(story),
            }
            for story in plan["stories"]
        ],
    }


def merge_public_and_internal(public_plan: dict[str, Any], internal_plan: dict[str, Any] | None) -> dict[str, Any]:
    if internal_plan is None:
        return public_plan

    internal_story_map = {story["id"]: story for story in internal_plan["stories"]}
    merged_stories = []
    for public_story in public_plan["stories"]:
        merged_story = dict(public_story)
        internal_story = internal_story_map.get(public_story["id"])
        if internal_story:
            for key in ("attempt_count", "last_run_id", "remaining_work", "last_review_reason", "verification_hints"):
                merged_story[key] = internal_story.get(key, merged_story.get(key))
            if story_is_complete(public_story):
                merged_story["status"] = "passed"
            elif internal_story.get("status") == "passed":
                merged_story["status"] = "pending"
            else:
                merged_story["status"] = internal_story.get("status", merged_story["status"])
            if public_story.get("suggested_tests") == ["manual verification required"] and internal_story.get("suggested_tests"):
                merged_story["suggested_tests"] = internal_story["suggested_tests"]
            if not merged_story.get("verification_hints"):
                merged_story["verification_hints"] = internal_story.get("verification_hints", [])
        merged_stories.append(merged_story)

    merged_plan = {
        "project_name": public_plan.get("project_name") or internal_plan.get("project_name"),
        "branch_name": public_plan.get("branch_name") if public_plan.get("branch_name") is not None else internal_plan.get("branch_name"),
        "source_format": internal_plan.get("source_format") or public_plan.get("source_format", "ralph_json"),
        "require_git": public_plan.get("require_git", internal_plan.get("require_git", True)),
        "stories": merged_stories,
    }
    validate_plan(merged_plan)
    return merged_plan


def load_internal_plan(default_project_name: str, default_require_git: bool) -> dict[str, Any] | None:
    if not INTERNAL_STATE_PATH.exists():
        return None
    return normalize_plan(
        read_json(INTERNAL_STATE_PATH),
        default_project_name=default_project_name,
        default_require_git=default_require_git,
    )


def load_config() -> dict[str, Any]:
    ensure_hidden_dirs()
    if not INTERNAL_CONFIG_PATH.exists():
        raise SystemExit("Missing .codex-ralph/config.json. Run `./ralph.sh init` first.")
    config = read_json(INTERNAL_CONFIG_PATH)
    repo_path = Path(config["repo_path"]).expanduser().resolve()
    if not repo_path.exists():
        raise SystemExit(f"Configured repo_path does not exist: {repo_path}")
    config["repo_path"] = str(repo_path)
    config.setdefault("require_git", True)
    config.setdefault("progress_tail_lines", 10)
    config.setdefault("max_diff_lines", 40)
    config.setdefault("max_test_output_chars", 4000)
    config.setdefault("command_timeout_seconds", 600)
    config.setdefault("browser_verify_command", "")
    return config


def require_timeout(config: dict[str, Any]) -> int:
    return int(config.get("command_timeout_seconds", 600))


def current_hidden_branch_name() -> str | None:
    if not INTERNAL_STATE_PATH.exists():
        return None
    try:
        state = read_json(INTERNAL_STATE_PATH)
    except json.JSONDecodeError:
        return None
    return state.get("branch_name") or state.get("branchName")


def archive_runtime_state(new_branch_name: str | None) -> None:
    current_branch = current_hidden_branch_name()
    tracked = [INTERNAL_CONFIG_PATH, INTERNAL_STATE_PATH, INTERNAL_RUNS_DIR, PUBLIC_PRD_PATH, PUBLIC_PROGRESS_PATH, PUBLIC_PROMPT_PATH]
    should_archive = bool(current_branch and new_branch_name and current_branch != new_branch_name)

    if should_archive:
        destination = INTERNAL_ARCHIVE_DIR / f"{utc_timestamp()}-{slugify_branch(current_branch)}"
        destination.mkdir(parents=True, exist_ok=True)
        for source in tracked:
            if source.exists():
                shutil.move(str(source), str(destination / source.name))
    else:
        for source in tracked:
            if source.is_dir():
                shutil.rmtree(source, ignore_errors=True)
            elif source.exists():
                source.unlink()
    ensure_hidden_dirs()


def save_runtime_state(config: dict[str, Any], plan: dict[str, Any]) -> None:
    ensure_hidden_dirs()
    write_json(INTERNAL_CONFIG_PATH, config)
    write_json(INTERNAL_STATE_PATH, plan)
    write_json(PUBLIC_PRD_PATH, export_public_plan(plan))


def read_progress_tail(limit: int) -> list[str]:
    if not PUBLIC_PROGRESS_PATH.exists():
        return []
    return tail_lines(PUBLIC_PROGRESS_PATH.read_text(encoding="utf-8"), limit)


def append_progress(entry: str) -> None:
    with PUBLIC_PROGRESS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(entry.rstrip() + "\n")


def build_config(args: argparse.Namespace, repo_path: Path) -> dict[str, Any]:
    return {
        "repo_path": str(repo_path),
        "planner_model": args.planner_model,
        "reviewer_model": args.reviewer_model or args.planner_model,
        "claude_model": args.claude_model,
        "default_test_commands": args.test_command or [],
        "require_git": not args.allow_non_git,
        "progress_tail_lines": 10,
        "max_diff_lines": 40,
        "max_test_output_chars": 4000,
        "command_timeout_seconds": 600,
        "browser_verify_command": args.browser_verify_command or "",
    }


def migrate_legacy_state_if_needed() -> None:
    if not LEGACY_STATE_DIR.exists():
        return
    if HIDDEN_DIR.exists() and PUBLIC_PRD_PATH.exists():
        return

    legacy_config_path = LEGACY_STATE_DIR / "config.json"
    legacy_prd_path = LEGACY_STATE_DIR / "prd.json"
    legacy_progress_path = LEGACY_STATE_DIR / "progress.txt"
    legacy_prompt_path = LEGACY_STATE_DIR / "prd.md"
    if not legacy_config_path.exists() or not legacy_prd_path.exists():
        return

    ensure_hidden_dirs()
    legacy_config = read_json(legacy_config_path)
    repo_path = Path(legacy_config.get("repo_path", ROOT)).expanduser().resolve()
    config = {
        "repo_path": str(repo_path),
        "planner_model": legacy_config.get("planner_model"),
        "reviewer_model": legacy_config.get("reviewer_model"),
        "claude_model": legacy_config.get("claude_model"),
        "default_test_commands": legacy_config.get("default_test_commands", []),
        "require_git": legacy_config.get("require_git", False),
        "progress_tail_lines": legacy_config.get("progress_tail_lines", 10),
        "max_diff_lines": legacy_config.get("max_diff_lines", 40),
        "max_test_output_chars": legacy_config.get("max_test_output_chars", 4000),
        "command_timeout_seconds": legacy_config.get("command_timeout_seconds", 600),
        "browser_verify_command": legacy_config.get("browser_verify_command", ""),
    }
    public_plan = normalize_plan(
        read_json(legacy_prd_path),
        default_project_name=repo_path.name,
        default_require_git=bool(config["require_git"]),
        source_format_override="canonical_v1",
    )
    save_runtime_state(config, public_plan)
    if legacy_progress_path.exists():
        shutil.copy2(legacy_progress_path, PUBLIC_PROGRESS_PATH)
    if legacy_prompt_path.exists() and not PUBLIC_PROMPT_PATH.exists():
        shutil.copy2(legacy_prompt_path, PUBLIC_PROMPT_PATH)

    destination = INTERNAL_ARCHIVE_DIR / "legacy-state" / utc_timestamp()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(LEGACY_STATE_DIR), str(destination))


def load_plan(config: dict[str, Any]) -> dict[str, Any]:
    migrate_legacy_state_if_needed()
    if not PUBLIC_PRD_PATH.exists() and INTERNAL_STATE_PATH.exists():
        internal = load_internal_plan(Path(config["repo_path"]).name, bool(config["require_git"]))
        if internal is None:
            raise SystemExit("Missing prd.json. Run `./ralph.sh init` first.")
        write_json(PUBLIC_PRD_PATH, export_public_plan(internal))
        return internal
    if not PUBLIC_PRD_PATH.exists():
        raise SystemExit("Missing prd.json. Run `./ralph.sh init` first.")

    public_plan = normalize_plan(
        read_json(PUBLIC_PRD_PATH),
        default_project_name=Path(config["repo_path"]).name,
        default_require_git=bool(config.get("require_git", True)),
        source_format_override="ralph_json",
    )
    internal_plan = load_internal_plan(Path(config["repo_path"]).name, bool(config.get("require_git", True)))
    merged = merge_public_and_internal(public_plan, internal_plan)
    healed = False
    if not lock_is_active():
        for story in merged["stories"]:
            if story.get("status") == "running":
                story["status"] = "blocked"
                story["last_review_reason"] = story.get("last_review_reason") or "Previous run exited before this story completed."
                remaining = [item for item in story.get("remaining_work", []) if item]
                note = "Review repo state and rerun this story after resolving the interrupted attempt."
                if note not in remaining:
                    remaining.append(note)
                story["remaining_work"] = remaining
                healed = True
    if clear_stale_lock_if_needed():
        healed = True
    if healed:
        validate_plan(merged)
    save_runtime_state(config, merged)
    return merged


def summarize_status(plan: dict[str, Any]) -> str:
    total = len(plan["stories"])
    done = sum(1 for story in plan["stories"] if story_is_complete(story))
    pending = total - done
    next_item = next_story(plan)
    parts = [f"{done}/{total} complete", f"{pending} pending"]
    if next_item:
        parts.append(f"next={next_item['id']}")
    return ", ".join(parts)


def next_story(plan: dict[str, Any]) -> dict[str, Any] | None:
    validate_plan(plan)
    stories = {story["id"]: story for story in plan["stories"]}
    for story in plan["stories"]:
        if story_is_complete(story):
            continue
        if story.get("status") == "running":
            continue
        dependencies = story.get("dependencies", [])
        if all(story_is_complete(stories[dep]) for dep in dependencies):
            return story
    return None


def find_story(plan: dict[str, Any], story_id: str) -> dict[str, Any]:
    for story in plan["stories"]:
        if story["id"] == story_id:
            return story
    raise PlanValidationError(f"Story not found: {story_id}")


def dependency_summary(plan: dict[str, Any], story: dict[str, Any]) -> list[dict[str, str]]:
    story_map = {item["id"]: item for item in plan["stories"]}
    return [
        {
            "id": story_map[dependency]["id"],
            "title": story_map[dependency]["title"],
            "status": story_map[dependency]["status"],
        }
        for dependency in story.get("dependencies", [])
    ]


def compact_story_summary(story: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": story["id"],
        "title": story["title"],
        "objective": story["objective"],
        "acceptance_criteria": story["acceptance_criteria"],
        "dependencies": story["dependencies"],
        "suggested_tests": story["suggested_tests"],
        "status": story["status"],
        "attempt_count": story["attempt_count"],
        "remaining_work": story["remaining_work"],
        "verification_hints": story.get("verification_hints", []),
    }


def compact_test_results(config: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    max_chars = int(config.get("max_test_output_chars", 4000))
    compacted = []
    for result in results:
        item = {
            "kind": result.get("kind"),
            "command": result.get("command"),
            "status": result.get("status"),
            "returncode": result.get("returncode"),
        }
        if result.get("stdout"):
            item["stdout"] = truncate_text(result["stdout"], max_chars)
        if result.get("stderr"):
            item["stderr"] = truncate_text(result["stderr"], max_chars)
        if result.get("message"):
            item["message"] = truncate_text(result["message"], max_chars)
        compacted.append(item)
    return compacted


def tests_all_passed(results: list[dict[str, Any]]) -> bool:
    for result in results:
        kind = result.get("kind")
        if kind == "command" and result.get("returncode") != 0:
            return False
        if kind == "browser" and result.get("status") != "passed":
            return False
    return True


def load_schema(schema_name: str) -> Path:
    return SCHEMAS_DIR / schema_name


def codex_exec(
    *,
    repo_path: Path,
    prompt: str,
    schema_path: Path,
    output_path: Path,
    model: str | None,
    timeout_seconds: int,
    phase: str,
) -> tuple[Any, CommandResult]:
    args = [
        "codex",
        "-a",
        "never",
        "-s",
        "danger-full-access",
        "exec",
        "-C",
        str(repo_path),
        "--skip-git-repo-check",
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
        "-",
    ]
    if model:
        args[1:1] = ["-m", model]
    try:
        result = run_command(args, cwd=repo_path, stdin_text=prompt, timeout_seconds=timeout_seconds)
    except ToolInvocationError as exc:
        raise ToolInvocationError(phase, str(exc), retryable=exc.retryable, details=exc.details) from exc

    if not output_path.exists():
        raise ToolInvocationError(phase, f"Codex did not write output file `{output_path.name}`", retryable=True)
    output_text = output_path.read_text(encoding="utf-8").strip()
    if not output_text:
        raise ToolInvocationError(phase, f"Codex wrote an empty output file `{output_path.name}`", retryable=True)
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ToolInvocationError(phase, "Codex returned invalid JSON", retryable=True, details=output_text) from exc
    validate_payload_against_schema(payload, schema_path)
    return payload, result


def claude_exec(
    *,
    repo_path: Path,
    prompt: str,
    schema_path: Path,
    model: str | None,
    timeout_seconds: int,
) -> tuple[Any, CommandResult]:
    args = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        schema_path.read_text(encoding="utf-8"),
        "--permission-mode",
        "bypassPermissions",
        "--dangerously-skip-permissions",
    ]
    if model:
        args.extend(["--model", model])
    args.append(prompt)
    try:
        result = run_command(args, cwd=repo_path, timeout_seconds=timeout_seconds)
    except ToolInvocationError as exc:
        raise ToolInvocationError("worker", str(exc), retryable=exc.retryable, details=exc.details) from exc
    stdout_text = result.stdout.strip()
    if not stdout_text:
        raise ToolInvocationError("worker", "Claude returned empty stdout", retryable=True)
    try:
        payload = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise ToolInvocationError("worker", "Claude returned invalid JSON", retryable=True, details=stdout_text) from exc
    structured = payload.get("structured_output", payload)
    validate_payload_against_schema(structured, schema_path)
    return structured, result


def build_plan_prompt(config: dict[str, Any], prd_text: str) -> str:
    tests = config.get("default_test_commands", [])
    return f"""You are the planning layer for a Codex-orchestrated Claude worker loop.

Read the PRD and produce a small, dependency-aware execution plan.

Rules:
- Return valid JSON only.
- Break the work into small stories that can be completed independently.
- Keep story IDs short and stable, like S1, S2, S3.
- Dependencies must reference prior story IDs.
- Suggested tests should be concrete shell commands when possible.
- Do not mark any story as done.

Repository path: {config["repo_path"]}
Default test commands: {json.dumps(tests, ensure_ascii=True)}

PRD:
{prd_text}
"""


def build_brief_prompt(
    config: dict[str, Any],
    plan: dict[str, Any],
    story: dict[str, Any],
    progress_lines: list[str],
    snapshot: dict[str, Any],
    has_agents_file: bool,
) -> str:
    compact_snapshot = compact_repo_snapshot(snapshot, int(config["max_diff_lines"]))
    browser_verify_command = str(config.get("browser_verify_command", "")).strip()
    return f"""You are the orchestration layer. Produce the next execution brief for Claude.

Rules:
- Return valid JSON only.
- The brief must focus on exactly one story.
- Reuse the story ID and title exactly.
- Keep test_commands as small as possible while still proving the story.
- Set verification_hints to include "browser" only when the story genuinely needs UI/browser verification.
- If browser verification is required and a browser_verify_command is configured, prefer that exact command or a tighter subset that matches the same repo-local Playwright path.
- claude_prompt must be ready to send directly to Claude as the worker instruction.
- The claude_prompt must forbid unrelated edits and require reporting changed files and blockers.
- If AGENTS.md exists, Claude may update it only when this story uncovers a durable repo convention or gotcha; otherwise it must not touch AGENTS.md.

Repository path: {config["repo_path"]}
AGENTS.md present: {has_agents_file}
Configured browser_verify_command: {browser_verify_command or '(unset)'}

Current story:
{json.dumps(compact_story_summary(story), indent=2, ensure_ascii=True)}

Dependency status:
{json.dumps(dependency_summary(plan, story), indent=2, ensure_ascii=True)}

Recent progress:
{json.dumps(progress_lines, indent=2, ensure_ascii=True)}

Repo evidence:
{json.dumps(compact_snapshot, indent=2, ensure_ascii=True)}
"""


def build_review_prompt(
    config: dict[str, Any],
    story: dict[str, Any],
    brief: dict[str, Any],
    worker_result: dict[str, Any],
    test_results: list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> str:
    brief_summary = {
        "story_id": brief["story_id"],
        "goal": brief["goal"],
        "acceptance_criteria": brief["acceptance_criteria"],
        "test_commands": brief["test_commands"],
        "verification_hints": brief.get("verification_hints", []),
    }
    return f"""You are the review layer for a Codex-orchestrated Claude worker loop.

Decide whether the current story is complete. Use only the deterministic evidence below.

Rules:
- Return valid JSON only.
- complete=true only if the acceptance criteria are satisfied and the evidence supports that conclusion.
- progress_entry must be one plain-text line suitable for progress.txt.
- remaining_work should be empty if complete=true.
- If the worker was blocked or failed, complete must be false.
- Treat repo_mode=non_git as explicit non-git evidence, not as a clean git snapshot.

Repository path: {config["repo_path"]}

Story:
{json.dumps(compact_story_summary(story), indent=2, ensure_ascii=True)}

Execution brief summary:
{json.dumps(brief_summary, indent=2, ensure_ascii=True)}

Claude worker result:
{json.dumps(worker_result, indent=2, ensure_ascii=True)}

Local test results:
{json.dumps(compact_test_results(config, test_results), indent=2, ensure_ascii=True)}

Repo evidence:
{json.dumps(compact_repo_snapshot(snapshot, int(config["max_diff_lines"])), indent=2, ensure_ascii=True)}
"""


def compose_claude_prompt(brief: dict[str, Any]) -> str:
    template = PUBLIC_CLAUDE_PATH.read_text(encoding="utf-8") if PUBLIC_CLAUDE_PATH.exists() else ""
    if not template.strip():
        return brief["claude_prompt"]
    return template.rstrip() + "\n\nExecution Brief:\n" + brief["claude_prompt"].strip() + "\n"


def test_commands_for_story(config: dict[str, Any], brief: dict[str, Any], story: dict[str, Any]) -> list[str]:
    explicit = [str(command).strip() for command in brief.get("test_commands", []) if str(command).strip()]
    if explicit:
        return explicit
    fallback = [str(command).strip() for command in story.get("suggested_tests", []) if str(command).strip()]
    if fallback:
        return fallback
    return [str(command).strip() for command in config.get("default_test_commands", []) if str(command).strip()]


def run_browser_verification(repo_path: Path, config: dict[str, Any], story: dict[str, Any]) -> dict[str, Any]:
    command = str(config.get("browser_verify_command", "")).strip()
    if not command:
        return {
            "kind": "browser",
            "command": None,
            "returncode": 1,
            "status": "missing",
            "message": "Browser verification is required for this story, but browser_verify_command is not configured.",
        }

    story_payload = export_public_plan(
        {
            "project_name": "story",
            "branch_name": None,
            "source_format": "ralph_json",
            "require_git": config.get("require_git", True),
            "stories": [story],
        }
    )["userStories"][0]
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".json") as handle:
        json.dump(story_payload, handle)
        temp_story = Path(handle.name)

    try:
        result = run_command(
            [
                sys.executable,
                str(BROWSER_VERIFY_SCRIPT),
                "--cwd",
                str(repo_path),
                "--story-file",
                str(temp_story),
                "--command",
                command,
            ],
            cwd=ROOT,
            check=False,
            timeout_seconds=require_timeout(config),
        )
    except ToolInvocationError as exc:
        return {
            "kind": "browser",
            "command": command,
            "returncode": 1,
            "status": "failed",
            "message": exc.details,
        }
    finally:
        temp_story.unlink(missing_ok=True)

    stdout = result.stdout.strip()
    if not stdout:
        return {
            "kind": "browser",
            "command": command,
            "returncode": 1,
            "status": "failed",
            "message": "Browser verifier returned empty stdout.",
            "stderr": result.stderr,
        }
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "kind": "browser",
            "command": command,
            "returncode": 1,
            "status": "failed",
            "message": "Browser verifier returned invalid JSON.",
            "stdout": stdout,
            "stderr": result.stderr,
        }

    return {
        "kind": "browser",
        "command": payload.get("command", command),
        "returncode": payload.get("returncode", result.returncode),
        "status": payload.get("status", "failed"),
        "message": payload.get("message", ""),
        "stdout": payload.get("stdout", ""),
        "stderr": payload.get("stderr", ""),
    }


def run_tests(repo_path: Path, commands: list[str], config: dict[str, Any], story: dict[str, Any], verification_hints: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    timeout_seconds = require_timeout(config)
    for command in commands:
        try:
            result = run_command(["zsh", "-lc", command], cwd=repo_path, check=False, timeout_seconds=timeout_seconds)
            results.append(
                {
                    "kind": "command",
                    "command": command,
                    "returncode": result.returncode,
                    "status": "passed" if result.returncode == 0 else "failed",
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
        except ToolInvocationError as exc:
            results.append(
                {
                    "kind": "command",
                    "command": command,
                    "returncode": 1,
                    "status": "failed",
                    "stdout": "",
                    "stderr": exc.details,
                }
            )

    if "browser" in verification_hints:
        results.append(run_browser_verification(repo_path, config, story))
    return results


def mark_story_running(plan: dict[str, Any], story_id: str, run_id: str) -> dict[str, Any]:
    story = find_story(plan, story_id)
    story["status"] = "running"
    story["attempt_count"] = int(story.get("attempt_count", 0)) + 1
    story["last_run_id"] = run_id
    story["remaining_work"] = []
    story["last_review_reason"] = ""
    return plan


def mark_story_terminal(
    plan: dict[str, Any],
    story_id: str,
    *,
    status: str,
    run_id: str,
    reason: str,
    remaining_work: list[str] | None = None,
) -> dict[str, Any]:
    if status not in STATUS_VALUES:
        raise PlanValidationError(f"Unsupported terminal status `{status}`")
    story = find_story(plan, story_id)
    story["status"] = status
    story["last_run_id"] = run_id
    story["last_review_reason"] = reason.strip()
    story["remaining_work"] = remaining_work or []
    return plan


def tool_failure_progress_line(story: dict[str, Any], run_id: str, exc: ToolInvocationError) -> str:
    return f"{story['id']} {story['title']} {exc.phase} failure in run {run_id}: {exc.details}"


def ensure_target_branch(repo_path: Path, plan: dict[str, Any], config: dict[str, Any]) -> None:
    branch_name = plan.get("branch_name")
    if not branch_name or not config.get("require_git", True):
        return
    snapshot = repo_snapshot(repo_path)
    if snapshot["repo_mode"] != "git":
        raise OrchestratorError("Target repository is not a git repo, but this plan requires git.")
    if snapshot["head_ref"] == branch_name:
        return

    exists = run_command(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=repo_path,
        check=False,
        timeout_seconds=require_timeout(config),
    )
    args = ["git", "switch", branch_name] if exists.returncode == 0 else ["git", "switch", "-c", branch_name]
    run_command(args, cwd=repo_path, timeout_seconds=require_timeout(config))


def maybe_commit_story(repo_path: Path, story: dict[str, Any], config: dict[str, Any], no_commit: bool) -> dict[str, Any]:
    if no_commit:
        return {"status": "skipped", "reason": "run invoked with --no-commit"}
    if not config.get("require_git", True):
        return {"status": "skipped", "reason": "non-git mode does not auto-commit"}

    snapshot = repo_snapshot(repo_path)
    if snapshot["repo_mode"] != "git":
        return {"status": "skipped", "reason": snapshot.get("git_error") or "target repo is not git"}
    if not snapshot["changed_files"]:
        return {"status": "skipped", "reason": "no changed files to commit"}

    timeout_seconds = require_timeout(config)
    run_command(["git", "add", "-A"], cwd=repo_path, timeout_seconds=timeout_seconds)
    commit_message = f"ralph: {story['id']} {story['title']}"
    commit = run_command(["git", "commit", "-m", commit_message], cwd=repo_path, check=False, timeout_seconds=timeout_seconds)
    if commit.returncode != 0:
        stderr = commit.stderr.strip() or commit.stdout.strip()
        if "nothing to commit" in stderr.lower():
            return {"status": "skipped", "reason": "git reported nothing to commit"}
        raise ToolInvocationError("git", f"Failed to commit story `{story['id']}`", details=stderr)
    sha = run_command(["git", "rev-parse", "--short", "HEAD"], cwd=repo_path, timeout_seconds=timeout_seconds)
    return {"status": "committed", "message": commit_message, "sha": sha.stdout.strip()}


@contextmanager
def state_lock() -> Any:
    ensure_hidden_dirs()
    clear_stale_lock_if_needed()
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        info = read_lock_info()
        if info and is_pid_alive(info.get("pid")):
            owner = f"pid={info['pid']}" if info.get("pid") else "unknown owner"
            raise SystemExit(f"Another run appears to be active: {LOCK_PATH} ({owner})") from exc
        clear_stale_lock_if_needed()
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, f"{os.getpid()} {utc_timestamp()}\n".encode("utf-8"))
        os.close(fd)
        yield
    finally:
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass


def select_prd_input(args: argparse.Namespace) -> tuple[str, str]:
    if args.import_prd_json:
        import_path = Path(args.import_prd_json).expanduser().resolve()
        return import_path.read_text(encoding="utf-8"), "ralph_json"
    if args.prd_file:
        return Path(args.prd_file).expanduser().read_text(encoding="utf-8"), "markdown"
    if args.goal:
        return args.goal.strip(), "goal"
    raise SystemExit("init requires --goal, --prd-file, or --import-prd-json")


def init_plan_from_goal_or_markdown(args: argparse.Namespace, config: dict[str, Any], prd_text: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    temp_output = HIDDEN_DIR / f".tmp-plan-{utc_timestamp()}.json"
    try:
        payload, raw = codex_exec(
            repo_path=Path(config["repo_path"]),
            prompt=build_plan_prompt(config, prd_text),
            schema_path=load_schema("plan.schema.json"),
            output_path=temp_output,
            model=config["planner_model"],
            timeout_seconds=require_timeout(config),
            phase="planner",
        )
        plan = normalize_plan(
            payload,
            default_project_name=Path(config["repo_path"]).name,
            default_require_git=config["require_git"],
            source_format_override="generated",
            branch_name_override=args.branch_name,
        )
        return plan, {"command": raw.to_dict()}
    finally:
        temp_output.unlink(missing_ok=True)


def init_plan_from_ralph_json(args: argparse.Namespace, config: dict[str, Any], prd_text: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        payload = json.loads(prd_text)
    except json.JSONDecodeError as exc:
        raise PlanValidationError("Imported Ralph prd.json is not valid JSON") from exc
    plan = normalize_plan(
        payload,
        default_project_name=Path(config["repo_path"]).name,
        default_require_git=config["require_git"],
        source_format_override="ralph_json",
        branch_name_override=args.branch_name,
    )
    return plan, None


def build_prompt_markdown(source_kind: str, prd_text: str, plan: dict[str, Any]) -> str:
    if source_kind in {"goal", "markdown"}:
        return prd_text.rstrip() + "\n"
    lines = [
        "# Imported Ralph PRD",
        "",
        f"- Branch: `{plan.get('branch_name') or 'none'}`",
        "- Stories:",
    ]
    for story in plan["stories"]:
        lines.append(f"  - `{story['id']}` {story['title']}")
    return "\n".join(lines) + "\n"


def write_init_transaction(config: dict[str, Any], plan: dict[str, Any], prompt_text: str, initial_progress: str) -> None:
    ensure_hidden_dirs()
    stage_root = Path(tempfile.mkdtemp(prefix="ralph-init-", dir=str(ROOT)))
    try:
        staged_hidden = stage_root / ".codex-ralph"
        staged_hidden.mkdir(parents=True, exist_ok=True)
        write_json(staged_hidden / "config.json", config)
        write_json(staged_hidden / "state.json", plan)
        (staged_hidden / "runs").mkdir(parents=True, exist_ok=True)
        write_json(stage_root / "prd.json", export_public_plan(plan))
        write_text(stage_root / "progress.txt", initial_progress.rstrip() + "\n")
        write_text(stage_root / "prompt.md", prompt_text.rstrip() + "\n")

        archive_runtime_state(plan.get("branch_name"))
        shutil.move(str(staged_hidden / "config.json"), str(INTERNAL_CONFIG_PATH))
        shutil.move(str(staged_hidden / "state.json"), str(INTERNAL_STATE_PATH))
        shutil.move(str(staged_hidden / "runs"), str(INTERNAL_RUNS_DIR))
        shutil.move(str(stage_root / "prd.json"), str(PUBLIC_PRD_PATH))
        shutil.move(str(stage_root / "progress.txt"), str(PUBLIC_PROGRESS_PATH))
        shutil.move(str(stage_root / "prompt.md"), str(PUBLIC_PROMPT_PATH))
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def print_status(plan: dict[str, Any], config: dict[str, Any]) -> None:
    print(f"repo: {config['repo_path']}")
    print(f"source_format: {plan['source_format']}")
    print(f"branch_name: {plan.get('branch_name') or '(none)'}")
    print(summarize_status(plan))
    for story in plan["stories"]:
        marker = "x" if story_is_complete(story) else " "
        print(f"[{marker}] {story['id']} {story['title']} ({story['status']}, attempts={story['attempt_count']})")


def init_command(args: argparse.Namespace) -> None:
    ensure_hidden_dirs()
    repo_path = Path(args.repo).expanduser().resolve()
    if not repo_path.exists():
        raise SystemExit(f"repo does not exist: {repo_path}")

    config = build_config(args, repo_path)
    snapshot = repo_snapshot(repo_path)
    if config["require_git"] and snapshot["repo_mode"] != "git":
        raise SystemExit("Target repo is not a git repository. Re-run `init` with `--allow-non-git` only for experimental mode.")

    prd_text, source_kind = select_prd_input(args)
    if source_kind == "ralph_json":
        plan, plan_raw = init_plan_from_ralph_json(args, config, prd_text)
    else:
        if not resolve_tool("codex"):
            raise SystemExit("`codex` is required on PATH for planner-driven init.")
        plan, plan_raw = init_plan_from_goal_or_markdown(args, config, prd_text)
    plan["require_git"] = config["require_git"]
    if args.branch_name:
        plan["branch_name"] = args.branch_name

    prompt_text = build_prompt_markdown(source_kind, prd_text, plan)
    initial_progress = f"[{utc_timestamp()}] Plan initialized for {repo_path.name} ({plan['source_format']})."
    write_init_transaction(config, plan, prompt_text, initial_progress)
    if plan_raw is not None:
        write_json(INTERNAL_RUNS_DIR / f"{utc_timestamp()}_plan_raw.json", plan_raw)
    print(f"Initialized. {summarize_status(plan)}")


def status_command(_: argparse.Namespace) -> None:
    config = load_config()
    plan = load_plan(config)
    print_status(plan, config)


def doctor_command(_: argparse.Namespace) -> None:
    migrate_legacy_state_if_needed()
    ensure_hidden_dirs()
    issues: list[str] = []
    stale_lock_cleared = clear_stale_lock_if_needed()
    if not INTERNAL_CONFIG_PATH.exists():
        issues.append("Missing .codex-ralph/config.json")
    else:
        config = load_config()
        plan = load_plan(config)
        snapshot = repo_snapshot(Path(config["repo_path"]))
        print_status(plan, config)
        print(f"repo_mode: {snapshot['repo_mode']}")
        if snapshot.get("git_error"):
            print(f"git_error: {snapshot['git_error']}")
        print(f"browser_verify_command: {config.get('browser_verify_command') or '(unset)'}")
        if config.get("require_git", True) and snapshot["repo_mode"] != "git":
            issues.append("Config requires git, but target repo is not a git worktree")
        if stale_lock_cleared:
            print("stale_lock: cleared")

    for tool_name in ("codex", "claude"):
        tool_path = resolve_tool(tool_name)
        print(f"{tool_name}: {tool_path or 'missing'}")
        if not tool_path:
            issues.append(f"`{tool_name}` not found on PATH")

    if LOCK_PATH.exists() and lock_is_active():
        issues.append(f"Active lock present: {LOCK_PATH}")

    for path in (PUBLIC_PRD_PATH, PUBLIC_PROGRESS_PATH, PUBLIC_PROMPT_PATH, PUBLIC_CLAUDE_PATH, PUBLIC_PRD_EXAMPLE_PATH):
        if not path.exists():
            issues.append(f"Missing public file: {path.name}")

    if issues:
        for issue in issues:
            print(f"issue: {issue}")
        raise SystemExit(1)
    print("doctor: ok")


def execute_dry_run(args: argparse.Namespace) -> None:
    config = load_config()
    plan = load_plan(config)
    story = next_story(plan)
    if not story:
        print("No runnable story remains.")
        return
    output_path = HIDDEN_DIR / f".tmp-brief-{utc_timestamp()}.json"
    try:
        brief, _ = codex_exec(
            repo_path=Path(config["repo_path"]),
            prompt=build_brief_prompt(
                config,
                plan,
                story,
                read_progress_tail(int(config["progress_tail_lines"])),
                repo_snapshot(Path(config["repo_path"])),
                (Path(config["repo_path"]) / "AGENTS.md").exists(),
            ),
            schema_path=load_schema("brief.schema.json"),
            output_path=output_path,
            model=config["planner_model"],
            timeout_seconds=require_timeout(config),
            phase="planner",
        )
        print(json.dumps(brief, indent=2, ensure_ascii=True))
    finally:
        output_path.unlink(missing_ok=True)


def process_story_attempt(config: dict[str, Any], plan: dict[str, Any], story_id: str, run_id: str, args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    repo_path = Path(config["repo_path"])
    story = find_story(plan, story_id)
    mark_story_running(plan, story_id, run_id)
    save_runtime_state(config, plan)

    timeout_seconds = require_timeout(config)
    brief_output = INTERNAL_RUNS_DIR / f"{run_id}_{story_id}_brief.json"
    progress_lines = read_progress_tail(int(config["progress_tail_lines"]))
    brief_prompt = build_brief_prompt(config, plan, story, progress_lines, repo_snapshot(repo_path), (repo_path / "AGENTS.md").exists())
    brief, brief_raw = codex_exec(
        repo_path=repo_path,
        prompt=brief_prompt,
        schema_path=load_schema("brief.schema.json"),
        output_path=brief_output,
        model=config["planner_model"],
        timeout_seconds=timeout_seconds,
        phase="planner",
    )
    write_json(INTERNAL_RUNS_DIR / f"{run_id}_{story_id}_brief_raw.json", {"command": brief_raw.to_dict()})

    worker_prompt = compose_claude_prompt(brief)
    worker_result, worker_raw = claude_exec(
        repo_path=repo_path,
        prompt=worker_prompt,
        schema_path=load_schema("worker.schema.json"),
        model=config["claude_model"],
        timeout_seconds=timeout_seconds,
    )
    write_json(INTERNAL_RUNS_DIR / f"{run_id}_{story_id}_worker.json", worker_result)
    write_json(INTERNAL_RUNS_DIR / f"{run_id}_{story_id}_worker_raw.json", {"command": worker_raw.to_dict()})

    tests = run_tests(repo_path, test_commands_for_story(config, brief, story), config, story, brief.get("verification_hints", []))
    write_json(INTERNAL_RUNS_DIR / f"{run_id}_{story_id}_tests.json", tests)

    review_output = INTERNAL_RUNS_DIR / f"{run_id}_{story_id}_review.json"
    review, review_raw = codex_exec(
        repo_path=repo_path,
        prompt=build_review_prompt(config, story, brief, worker_result, tests, repo_snapshot(repo_path)),
        schema_path=load_schema("review.schema.json"),
        output_path=review_output,
        model=config["reviewer_model"],
        timeout_seconds=timeout_seconds,
        phase="reviewer",
    )
    write_json(INTERNAL_RUNS_DIR / f"{run_id}_{story_id}_review_raw.json", {"command": review_raw.to_dict()})

    test_gate_ok = tests_all_passed(tests)
    review_complete = bool(review["complete"]) and test_gate_ok
    reason = str(review["reason"]).strip()
    if not test_gate_ok:
        reason = f"{reason} Tests or browser verification did not fully pass." if reason else "Tests or browser verification did not fully pass."

    if review_complete:
        mark_story_terminal(plan, story_id, status="passed", run_id=run_id, reason=reason)
        save_runtime_state(config, plan)
        append_progress(review["progress_entry"])
        commit_result = maybe_commit_story(repo_path, story, config, args.no_commit)
        if commit_result["status"] == "committed":
            append_progress(f"{story_id} committed as {commit_result['sha']} with `{commit_result['message']}`.")
        elif commit_result["status"] == "skipped":
            append_progress(f"{story_id} commit skipped: {commit_result['reason']}.")
        print(f"{story_id}: complete=True | {reason}")
        return plan, True

    remaining_work = [str(item).strip() for item in review.get("remaining_work", []) if str(item).strip()]
    mark_story_terminal(plan, story_id, status="blocked", run_id=run_id, reason=reason, remaining_work=remaining_work)
    save_runtime_state(config, plan)
    append_progress(review["progress_entry"])
    print(f"{story_id}: complete=False | {reason}")
    return plan, False


def run_command_loop(args: argparse.Namespace) -> None:
    if args.dry_run:
        execute_dry_run(args)
        return

    config = load_config()
    plan = load_plan(config)
    repo_path = Path(config["repo_path"])
    if not resolve_tool("codex"):
        raise SystemExit("`codex` is required on PATH.")
    if not resolve_tool("claude"):
        raise SystemExit("`claude` is required on PATH.")

    current_story_id: str | None = None
    current_run_id: str | None = None
    try:
        with state_lock():
            if config.get("require_git", True) and repo_snapshot(repo_path)["repo_mode"] != "git":
                raise SystemExit("Configured repo requires git, but target repo is not a git worktree.")
            ensure_target_branch(repo_path, plan, config)
            steps_taken = 0
            while steps_taken < args.max_steps:
                plan = load_plan(config)
                story = next_story(plan)
                if not story:
                    print("No runnable story remains.")
                    break

                story_id = story["id"]
                attempt = 0
                succeeded = False
                while attempt <= args.max_retries:
                    attempt += 1
                    run_id = utc_timestamp()
                    current_story_id = story_id
                    current_run_id = run_id
                    try:
                        plan, succeeded = process_story_attempt(config, plan, story_id, run_id, args)
                        current_story_id = None
                        current_run_id = None
                        break
                    except ToolInvocationError as exc:
                        remaining = [exc.details] if exc.details else []
                        status = "failed" if exc.retryable else "blocked"
                        mark_story_terminal(plan, story_id, status=status, run_id=run_id, reason=exc.details, remaining_work=remaining)
                        save_runtime_state(config, plan)
                        append_progress(tool_failure_progress_line(story, run_id, exc))
                        print(f"{story_id}: {exc.phase} failure | {exc.details}")
                        current_story_id = None
                        current_run_id = None
                        if exc.retryable and attempt <= args.max_retries:
                            print(f"Retrying {story_id} ({attempt}/{args.max_retries})")
                            continue
                        break

                if not succeeded:
                    print("Stopping because the current story did not pass review.")
                    break
                steps_taken += 1
    except KeyboardInterrupt:
        if current_story_id and current_run_id:
            plan = load_plan(config)
            story = find_story(plan, current_story_id)
            if story.get("status") == "running":
                mark_story_terminal(
                    plan,
                    current_story_id,
                    status="blocked",
                    run_id=current_run_id,
                    reason="Run interrupted before the story completed.",
                    remaining_work=["Review repo state and rerun this story after the interrupted attempt."],
                )
                save_runtime_state(config, plan)
                append_progress(f"{current_story_id} interrupted in run {current_run_id}.")
        raise SystemExit(130)

    print(summarize_status(load_plan(config)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal Codex planner + Claude worker runtime.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize hidden runtime state and root Ralph-compatible files")
    init_parser.add_argument("--repo", default=".", help="Target repository path")
    init_parser.add_argument("--goal", help="Inline PRD text or project goal")
    init_parser.add_argument("--prd-file", help="Path to a PRD markdown file")
    init_parser.add_argument("--import-prd-json", help="Path to a Ralph-compatible prd.json file")
    init_parser.add_argument("--branch-name", help="Feature branch to switch/create on first run")
    init_parser.add_argument("--allow-non-git", action="store_true", help="Allow experimental non-git mode")
    init_parser.add_argument("--planner-model", help="Codex planner model override")
    init_parser.add_argument("--reviewer-model", help="Codex reviewer model override")
    init_parser.add_argument("--claude-model", help="Claude worker model override")
    init_parser.add_argument("--test-command", action="append", help="Default test command. Repeatable.")
    init_parser.add_argument("--browser-verify-command", help="Shell command used for browser verification when UI stories require it")
    init_parser.set_defaults(func=init_command)

    run_parser = subparsers.add_parser("run", help="Run one or more execution loops")
    run_parser.add_argument("--max-steps", type=int, default=1, help="Maximum runnable stories")
    run_parser.add_argument("--max-retries", type=int, default=0, help="Retries for retryable tooling failures")
    run_parser.add_argument("--no-commit", action="store_true", help="Skip auto-commit after a passing story")
    run_parser.add_argument("--dry-run", action="store_true", help="Print the next brief and stop")
    run_parser.set_defaults(func=run_command_loop)

    status_parser = subparsers.add_parser("status", help="Show current plan progress")
    status_parser.set_defaults(func=status_command)

    doctor_parser = subparsers.add_parser("doctor", help="Validate runtime state, tools, and public files")
    doctor_parser.set_defaults(func=doctor_command)
    return parser


def main() -> None:
    ensure_hidden_dirs()
    migrate_legacy_state_if_needed()
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except OrchestratorError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
