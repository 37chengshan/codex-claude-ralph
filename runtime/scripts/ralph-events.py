#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_dir(repo: Path) -> Path:
    return repo / ".codex-ralph"


def events_path(repo: Path) -> Path:
    return state_dir(repo) / "events.jsonl"


def state_path(repo: Path) -> Path:
    return state_dir(repo) / "state.json"


def plan_score_path(repo: Path) -> Path:
    return state_dir(repo) / "plan_score.json"


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def append_event(repo: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload = {k: v for k, v in payload.items() if v is not None}
    payload.setdefault("timestamp", utc_now())
    path = events_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def read_events(repo: Path) -> list[dict[str, Any]]:
    path = events_path(repo)
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            result.append(payload)
    return result


def build_status(repo: Path) -> dict[str, Any]:
    state = read_json(state_path(repo)) or {}
    events = read_events(repo)
    last_event = events[-1] if events else None
    plan_score = read_json(plan_score_path(repo))
    return {
        "stage": state.get("stage", last_event.get("stage") if last_event else "unknown"),
        "status": state.get("status", last_event.get("status") if last_event else "unknown"),
        "message": state.get("message", last_event.get("message") if last_event else ""),
        "discussion": {
            "ready": state.get("discussion_ready", False),
            "summary": state.get("discussion_summary", ""),
            "open_questions": state.get("open_questions", []),
            "missing_decisions": state.get("missing_decisions", []),
            "current_question": (state.get("discussion") or {}).get("current_question") if isinstance(state.get("discussion"), dict) else None,
        },
        "scorecard": plan_score if isinstance(plan_score, dict) else None,
        "current_story": state.get("current_story"),
        "progress": state.get("progress", {"completed": 0, "total": 0}),
        "plan_score": plan_score if isinstance(plan_score, dict) else None,
        "last_event": last_event,
        "events_path": str(events_path(repo)),
        "next_action": state.get("next_action"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Append and read Ralph stage events.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    append_parser = sub.add_parser("append")
    append_parser.add_argument("--repo", required=True)
    append_parser.add_argument("--stage", required=True)
    append_parser.add_argument("--status", required=True)
    append_parser.add_argument("--message", required=True)
    append_parser.add_argument("--run-id")
    append_parser.add_argument("--story-id")
    append_parser.add_argument("--next")
    append_parser.add_argument("--artifact")

    status_parser = sub.add_parser("status")
    status_parser.add_argument("--repo", required=True)
    status_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    repo = Path(args.repo).expanduser().resolve()

    if args.cmd == "append":
        payload = append_event(
            repo,
            {
                "run_id": args.run_id,
                "stage": args.stage,
                "story_id": args.story_id,
                "status": args.status,
                "message": args.message,
                "next": args.next,
                "artifact": args.artifact,
            },
        )
        print(json.dumps(payload, ensure_ascii=False))
        return

    payload = build_status(repo)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{payload['stage']}: {payload['status']} - {payload['message']}")


if __name__ == "__main__":
    main()
