#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_event(repo: Path, *, stage: str, status: str, message: str, story_id: str | None = None, artifact: str | None = None, next_stage: str | None = None) -> None:
    path = repo / ".codex-ralph" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": utc_now(),
        "stage": stage,
        "status": status,
        "story_id": story_id,
        "message": message,
        "artifact": artifact,
        "next": next_stage,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_text(path: Path | None) -> str:
    if not path:
        return ""
    return path.read_text(encoding="utf-8")


def read_json(path: Path | None) -> Any:
    if not path:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_prompt(*, story_id: str, story_title: str, prompt_text: str, brief_payload: Any) -> str:
    return "\n".join(
        [
            "You are Claude Code running as the Ralph worker.",
            "",
            "Rules:",
            "- Work on exactly one story.",
            "- Do not re-plan the whole project.",
            "- Make the smallest safe change that satisfies the brief.",
            "- Do not edit unrelated files.",
            "- If blocked, report blockers instead of pretending success.",
            "- Return JSON only.",
            "",
            "Required JSON shape:",
            json.dumps(
                {
                    "structured_output": {
                        "status": "success | blocked | failed",
                        "summary": "short summary",
                        "changed_files": ["path"],
                        "tests_run": ["command"],
                        "blockers": ["reason"],
                    }
                },
                indent=2,
            ),
            "",
            f"Story ID: {story_id}",
            f"Story Title: {story_title}",
            "",
            "Brief JSON:",
            json.dumps(brief_payload, indent=2, ensure_ascii=False) if brief_payload is not None else "{}",
            "",
            "Additional Prompt:",
            prompt_text.strip(),
            "",
        ]
    ).rstrip() + "\n"


def extract_first_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        char = text[idx]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : idx + 1]
                try:
                    parsed = json.loads(candidate)
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def normalize_worker_payload(parsed: dict[str, Any] | None, stdout: str, stderr: str, returncode: int) -> tuple[dict[str, Any], str]:
    if parsed is None:
        return (
            {
                "structured_output": {
                    "status": "failed",
                    "summary": "Claude did not return parseable JSON.",
                    "changed_files": [],
                    "tests_run": [],
                    "blockers": ["invalid_json"],
                },
                "parse_error": True,
                "stdout_excerpt": stdout[-4000:],
                "stderr_excerpt": stderr[-4000:],
                "returncode": returncode,
            },
            "failed",
        )

    structured = parsed["structured_output"] if isinstance(parsed.get("structured_output"), dict) else parsed
    status = str(structured.get("status", "success" if returncode == 0 else "failed")).lower()
    if status in {"complete", "completed", "pass", "passed"}:
        status = "success"
    if status not in {"success", "blocked", "failed"}:
        status = "success" if returncode == 0 else "failed"

    normalized = {
        "structured_output": {
            "status": status,
            "summary": str(structured.get("summary", "")),
            "changed_files": structured.get("changed_files", []) if isinstance(structured.get("changed_files", []), list) else [],
            "tests_run": structured.get("tests_run", []) if isinstance(structured.get("tests_run", []), list) else [],
            "blockers": structured.get("blockers", []) if isinstance(structured.get("blockers", []), list) else [],
        },
        "returncode": returncode,
    }
    return normalized, status


def build_command(template: str | None, prompt: str, prompt_file: Path, model: str | None) -> list[str]:
    env_template = template or os.environ.get("RALPH_CLAUDE_COMMAND", "").strip()
    if env_template:
        rendered = env_template.replace("{prompt}", prompt).replace("{prompt_file}", str(prompt_file))
        return rendered.split()
    command = ["claude", "-p", prompt]
    if model:
        command.extend(["--model", model])
    return command


def run_worker(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    cwd = Path(args.cwd).resolve()
    output = Path(args.output).resolve()
    raw_output = Path(args.raw_output).resolve() if args.raw_output else output.with_name(output.stem + "_raw.json")

    if shutil.which("claude") is None and not (args.claude_command or os.environ.get("RALPH_CLAUDE_COMMAND")):
        append_event(repo, stage="worker", status="failed", story_id=args.story_id, message="Claude CLI was not found in PATH.")
        print("Claude CLI was not found in PATH.", file=sys.stderr)
        return 127

    brief_payload = read_json(Path(args.brief_file).resolve()) if args.brief_file else None
    prompt_text = read_text(Path(args.prompt_file).resolve()) if args.prompt_file else ""
    prompt = build_prompt(
        story_id=args.story_id,
        story_title=args.story_title or args.story_id,
        prompt_text=prompt_text,
        brief_payload=brief_payload,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.parent.mkdir(parents=True, exist_ok=True)

    append_event(repo, stage="worker", status="running", story_id=args.story_id, message=f"Claude Code is implementing {args.story_id}.", next_stage="worker_complete")

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".md") as handle:
        handle.write(prompt)
        prompt_file = Path(handle.name)

    command = build_command(args.claude_command, prompt, prompt_file, args.model)
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=args.timeout,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        raw_output.write_text(
            json.dumps(
                {
                    "args": command,
                    "cwd": str(cwd),
                    "timeout": args.timeout,
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr or "",
                    "returncode": None,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        payload = {
            "structured_output": {
                "status": "failed",
                "summary": f"Claude timed out after {args.timeout}s.",
                "changed_files": [],
                "tests_run": [],
                "blockers": ["timeout"],
            }
        }
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        append_event(repo, stage="worker", status="failed", story_id=args.story_id, message=payload["structured_output"]["summary"], artifact=str(raw_output))
        return 124
    finally:
        try:
            prompt_file.unlink(missing_ok=True)
        except OSError:
            pass

    raw = {
        "args": command,
        "cwd": str(cwd),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    raw_output.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    parsed = extract_first_json_object(completed.stdout)
    normalized, status = normalize_worker_payload(parsed, completed.stdout, completed.stderr, completed.returncode)
    output.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    event_status = "passed" if status == "success" and completed.returncode == 0 else ("blocked" if status == "blocked" else "failed")
    summary = normalized["structured_output"].get("summary") or f"Claude worker {event_status}."
    append_event(
        repo,
        stage="worker",
        status=event_status,
        story_id=args.story_id,
        message=summary,
        artifact=str(output),
        next_stage="tests" if event_status == "passed" else None,
    )

    if completed.returncode != 0 or event_status == "failed":
        return completed.returncode or 5
    if event_status == "blocked":
        return 6
    return 0


def doctor(args: argparse.Namespace) -> int:
    command = args.claude_command or os.environ.get("RALPH_CLAUDE_COMMAND")
    found = bool(command) or shutil.which("claude") is not None
    payload = {
        "claude_available": found,
        "claude_path": shutil.which("claude"),
        "custom_command": command or None,
    }
    print(json.dumps(payload, indent=2))
    return 0 if found else 127


def main() -> None:
    parser = argparse.ArgumentParser(description="Ralph Claude Code worker bridge.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--claude-command")

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--repo", required=True)
    run_parser.add_argument("--cwd", required=True)
    run_parser.add_argument("--story-id", required=True)
    run_parser.add_argument("--story-title", default="")
    run_parser.add_argument("--brief-file")
    run_parser.add_argument("--prompt-file")
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--raw-output")
    run_parser.add_argument("--timeout", type=int, default=600)
    run_parser.add_argument("--model")
    run_parser.add_argument("--claude-command")

    args = parser.parse_args()
    if args.cmd == "doctor":
        raise SystemExit(doctor(args))
    raise SystemExit(run_worker(args))


if __name__ == "__main__":
    main()
