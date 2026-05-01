#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_root() -> Path:
    return Path(os.environ.get("TARGET_REPO", os.getcwd())).resolve()


def runs_dir(repo: Path) -> Path:
    path = repo / ".codex-ralph" / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def append_event(stage: str, status: str, message: str, *, story_id: str | None = None, artifact: str | None = None, next_stage: str | None = None) -> None:
    repo = repo_root()
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
    payload = {k: v for k, v in payload.items() if v is not None}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def extract_prompt(argv: list[str]) -> str:
    for i, item in enumerate(argv):
        if item in {"-p", "--print", "--prompt"} and i + 1 < len(argv):
            return argv[i + 1]
        if item.startswith("--prompt="):
            return item.split("=", 1)[1]
    return " ".join(argv)


def infer_story(prompt: str) -> tuple[str | None, str | None]:
    story_id = None
    story_title = None

    for pattern in [
        r'"story_id"\s*:\s*"([^"]+)"',
        r'"id"\s*:\s*"([^"]+)"',
        r"Story ID:\s*([A-Za-z0-9_.-]+)",
        r"story\s+([A-Za-z0-9_.-]+)",
    ]:
        match = re.search(pattern, prompt, re.IGNORECASE)
        if match:
            story_id = match.group(1)
            break

    for pattern in [
        r'"title"\s*:\s*"([^"]+)"',
        r"Story Title:\s*(.+)",
    ]:
        match = re.search(pattern, prompt, re.IGNORECASE)
        if match:
            story_title = match.group(1).strip().splitlines()[0][:120]
            break

    return story_id, story_title


def extract_first_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    start = stripped.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(stripped)):
        char = stripped[idx]
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
                candidate = stripped[start : idx + 1]
                try:
                    parsed = json.loads(candidate)
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def worker_status(parsed: dict[str, Any] | None, returncode: int) -> tuple[str, str]:
    if parsed is None:
        return "failed", "Claude Code returned non-JSON output."
    structured = parsed.get("structured_output", parsed)
    if not isinstance(structured, dict):
        return "failed", "Claude Code returned JSON with unsupported shape."
    raw_status = str(structured.get("status", "")).lower()
    summary = str(structured.get("summary", "")).strip()
    if raw_status in {"success", "complete", "completed", "pass", "passed"} and returncode == 0:
        return "passed", summary or "Claude Code completed the worker step."
    if raw_status == "blocked":
        return "blocked", summary or "Claude Code blocked the worker step."
    if returncode != 0:
        return "failed", summary or f"Claude Code exited with {returncode}."
    return "passed", summary or "Claude Code completed the worker step."


def main() -> int:
    real_claude = os.environ.get("RALPH_REAL_CLAUDE")
    if not real_claude:
        print("RALPH_REAL_CLAUDE is not set; cannot proxy Claude Code.", file=sys.stderr)
        return 127

    repo = repo_root()
    prompt = extract_prompt(sys.argv[1:])
    story_id, story_title = infer_story(prompt)

    append_event("worker", "running", f"Claude Code is implementing {story_id or 'the current story'}.", story_id=story_id, next_stage="worker_result")

    timeout = int(os.environ.get("RALPH_CLAUDE_TIMEOUT_SECONDS", "600"))
    command = [real_claude, *sys.argv[1:]]

    try:
        completed = subprocess.run(
            command,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env={k: v for k, v in os.environ.items() if k != "RALPH_REAL_CLAUDE"},
        )
    except subprocess.TimeoutExpired as exc:
        artifact = runs_dir(repo) / f"{utc_now().replace(':', '').replace('-', '')}_{story_id or 'unknown'}_claude_proxy_raw.json"
        artifact.write_text(
            json.dumps(
                {
                    "args": command,
                    "cwd": os.getcwd(),
                    "timeout": timeout,
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr or "",
                    "returncode": None,
                    "story_id": story_id,
                    "story_title": story_title,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        append_event("worker", "failed", f"Claude Code timed out after {timeout}s.", story_id=story_id, artifact=str(artifact))
        print(exc.stdout or "", end="")
        print(exc.stderr or "", end="", file=sys.stderr)
        return 124

    parsed = extract_first_json_object(completed.stdout)
    event_status, message = worker_status(parsed, completed.returncode)

    artifact = runs_dir(repo) / f"{utc_now().replace(':', '').replace('-', '')}_{story_id or 'unknown'}_claude_proxy_raw.json"
    artifact.write_text(
        json.dumps(
            {
                "args": command,
                "cwd": os.getcwd(),
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "parsed_json": parsed,
                "story_id": story_id,
                "story_title": story_title,
                "event_status": event_status,
                "message": message,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    append_event("worker", event_status, message, story_id=story_id, artifact=str(artifact), next_stage="tests" if event_status == "passed" else None)

    print(completed.stdout, end="")
    print(completed.stderr, end="", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
