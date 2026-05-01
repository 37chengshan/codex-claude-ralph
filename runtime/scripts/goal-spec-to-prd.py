#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"GoalSpec must be JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("GoalSpec must be a JSON object")
    return payload


def require_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"GoalSpec missing non-empty `{key}`")
    return value.strip()


def list_of_strings(payload: dict[str, Any], key: str, *, required: bool = False) -> list[str]:
    value = payload.get(key, [])
    if required and not value:
        raise SystemExit(f"GoalSpec missing non-empty `{key}`")
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise SystemExit(f"GoalSpec `{key}` must be a list of non-empty strings")
    return [item.strip() for item in value]


def normalize_stories(payload: dict[str, Any]) -> list[dict[str, Any]]:
    stories = payload.get("stories")
    if stories is None:
        goal = require_text(payload, "goal")
        acceptance = list_of_strings(payload, "acceptance_criteria", required=True)
        verification = list_of_strings(payload, "verification", required=False) or ["manual verification required"]
        return [
            {
                "id": "S1",
                "title": payload.get("title") or goal[:80],
                "description": goal,
                "acceptance_criteria": acceptance,
                "dependencies": [],
                "suggested_tests": verification,
                "passes": False,
            }
        ]

    if not isinstance(stories, list) or not stories:
        raise SystemExit("GoalSpec `stories` must be a non-empty array")
    result: list[dict[str, Any]] = []
    for index, story in enumerate(stories, start=1):
        if not isinstance(story, dict):
            raise SystemExit("Each story must be an object")
        story_id = str(story.get("id") or f"S{index}")
        title = str(story.get("title") or story.get("goal") or story_id)
        description = str(story.get("description") or story.get("goal") or title)
        acceptance = story.get("acceptance_criteria") or story.get("acceptanceCriteria") or []
        if not isinstance(acceptance, list) or not acceptance:
            raise SystemExit(f"Story `{story_id}` requires acceptance_criteria")
        result.append(
            {
                "id": story_id,
                "title": title,
                "description": description,
                "acceptance_criteria": [str(item) for item in acceptance],
                "dependencies": [str(item) for item in story.get("dependencies", [])],
                "suggested_tests": [str(item) for item in story.get("suggested_tests", story.get("verification", []))] or ["manual verification required"],
                "passes": bool(story.get("passes", False)),
            }
        )
    return result


def build_prompt(payload: dict[str, Any], prd: dict[str, Any]) -> str:
    lines = [
        "# Ralph GoalSpec",
        "",
        "## Goal",
        require_text(payload, "goal"),
        "",
        "## Allowed Scope",
        *[f"- {item}" for item in list_of_strings(payload, "allowed_scope")],
        "",
        "## Forbidden Scope",
        *[f"- {item}" for item in list_of_strings(payload, "forbidden_scope")],
        "",
        "## Acceptance Criteria",
    ]
    for story in prd["userStories"]:
        lines.append(f"- {story['id']}: {story['title']}")
        for criterion in story["acceptance_criteria"]:
            lines.append(f"  - {criterion}")

    if payload.get("codebase_evidence"):
        lines.extend(["", "## Codebase Evidence"])
        for evidence in payload["codebase_evidence"]:
            if isinstance(evidence, dict):
                file_ref = evidence.get("file", "")
                line_ref = evidence.get("lines", "")
                claim = evidence.get("claim", "")
                lines.append(f"- {file_ref}:{line_ref} - {claim}")

    if payload.get("risks"):
        lines.extend(["", "## Risks"])
        for risk in payload["risks"]:
            if isinstance(risk, dict):
                lines.append(f"- {risk.get('risk', '')}: {risk.get('mitigation', '')}")
            else:
                lines.append(f"- {risk}")

    if payload.get("discussion_summary"):
        lines.extend(["", "## Discussion Summary", f"- {payload.get('discussion_summary', '')}"])
    if payload.get("open_questions"):
        lines.extend(["", "## Open Questions"])
        for question in payload.get("open_questions", []):
            lines.append(f"- {question}")
    if payload.get("missing_decisions"):
        lines.extend(["", "## Missing Decisions"])
        for item in payload.get("missing_decisions", []):
            lines.append(f"- {item}")

    lines.extend(["", "## User Confirmation", f"- confirmed: {bool(payload.get('user_confirmation', False))}"])
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert GoalSpec JSON into Ralph-compatible prd.json.")
    parser.add_argument("--goal-spec", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--prompt-output")
    parser.add_argument("--plan-score-output")
    args = parser.parse_args()

    goal_spec_path = Path(args.goal_spec)
    payload = load_json(goal_spec_path)

    require_text(payload, "goal")
    if payload.get("stories") is None:
        list_of_strings(payload, "acceptance_criteria", required=True)

    prd = {
        "projectName": payload.get("project_name") or payload.get("projectName") or "ralph-goal",
        "branchName": payload.get("branch_name") or payload.get("branchName"),
        "userStories": normalize_stories(payload),
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(prd, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.prompt_output:
        prompt_output = Path(args.prompt_output)
        prompt_output.parent.mkdir(parents=True, exist_ok=True)
        prompt_output.write_text(build_prompt(payload, prd), encoding="utf-8")

    if args.plan_score_output:
        plan_score = payload.get("plan_score")
        plan_score_output = Path(args.plan_score_output)
        plan_score_output.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(plan_score, dict):
            plan_score_output.write_text(json.dumps(plan_score, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        else:
            plan_score_output.write_text("", encoding="utf-8")


if __name__ == "__main__":
    main()
