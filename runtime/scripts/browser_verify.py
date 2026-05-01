#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


SHELL_METACHARS = set("|&;<>()$`")


def _json_argv(command: str) -> list[str] | None:
    try:
        payload = json.loads(command)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list) or not payload or not all(isinstance(item, str) for item in payload):
        return None
    return payload


def _rebuild_python_command(command: str) -> list[str] | None:
    raw_parts = command.split()
    if len(raw_parts) < 2:
        return None
    interpreter = raw_parts[0]
    if Path(interpreter).name not in {"python", "python3"}:
        return None

    script_parts = raw_parts[1:]
    for stop in range(len(script_parts), 0, -1):
        candidate = " ".join(script_parts[:stop])
        if Path(candidate).exists():
            return [interpreter, candidate, *script_parts[stop:]]
    return None


def _looks_like_plain_argv(command: str) -> bool:
    return not any(char in command for char in SHELL_METACHARS)


def _resolve_command(command: str) -> tuple[list[str] | str, bool]:
    argv = _json_argv(command)
    if argv:
        return argv, False

    rebuilt = _rebuild_python_command(command)
    if rebuilt:
        return rebuilt, False

    if _looks_like_plain_argv(command):
        return shlex.split(command), False

    return command, True


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a browser verification command and emit structured JSON.")
    parser.add_argument("--cwd", required=True, help="Working directory for the browser verification command")
    parser.add_argument("--story-file", required=True, help="Path to a JSON file with the current public story payload")
    parser.add_argument("--command", required=True, help="Shell command to execute for browser verification")
    args = parser.parse_args()

    story_path = Path(args.story_file)
    story_payload = json.loads(story_path.read_text(encoding="utf-8"))
    env = os.environ.copy()
    env["RALPH_BROWSER_STORY_JSON"] = json.dumps(story_payload, ensure_ascii=True)
    env["RALPH_BROWSER_STORY_ID"] = str(story_payload.get("id", ""))
    env["RALPH_BROWSER_STORY_TITLE"] = str(story_payload.get("title", ""))

    command, use_shell = _resolve_command(args.command)
    if use_shell:
        completed = subprocess.run(
            ["zsh", "-lc", command],
            cwd=args.cwd,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
    else:
        completed = subprocess.run(
            command,
            cwd=args.cwd,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    stdout = completed.stdout.strip()
    if stdout:
        try:
            payload = json.loads(stdout)
            if isinstance(payload, dict) and payload.get("status") in {"passed", "failed", "missing"}:
                payload.setdefault("command", args.command)
                payload.setdefault("returncode", completed.returncode)
                print(json.dumps(payload))
                return
        except json.JSONDecodeError:
            pass

    payload = {
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": args.command,
        "returncode": completed.returncode,
        "message": "Browser verification command completed." if completed.returncode == 0 else "Browser verification command failed.",
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
