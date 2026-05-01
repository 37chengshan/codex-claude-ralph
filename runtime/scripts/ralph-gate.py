#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


THRESHOLD = 85
GATE_THRESHOLDS = {"epistemic": 70, "deontic": 70, "dialectical": 60}


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON: {path}: {exc}") from exc


def evaluate(score: dict[str, Any] | None, goal_spec: dict[str, Any] | None, threshold: int) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not isinstance(goal_spec, dict):
        reasons.append("Missing goal_spec.json")
    else:
        if not bool(goal_spec.get("discussion_ready", False)):
            reasons.append("GoalSpec discussion_ready is false")
        open_questions = goal_spec.get("open_questions", [])
        if not isinstance(open_questions, list):
            reasons.append("goal_spec.open_questions must be an array")
        elif open_questions:
            reasons.append("Open questions remain: " + "; ".join(str(item) for item in open_questions))
        missing_decisions = goal_spec.get("missing_decisions", [])
        if not isinstance(missing_decisions, list):
            reasons.append("goal_spec.missing_decisions must be an array")
        elif missing_decisions:
            reasons.append("Missing decisions remain: " + "; ".join(str(item) for item in missing_decisions))
    if score is None:
        reasons.append("Missing plan_score.json")
    else:
        total = score.get("total")
        decision = str(score.get("decision", "")).lower()
        hard_blockers = score.get("hard_blockers", [])
        effective_threshold = int(score.get("threshold", threshold))
        if score.get("discussion_ready") is False:
            reasons.append("plan_score marks discussion as not ready")
        gates = score.get("gates", {})
        for gate_name, gate_threshold in GATE_THRESHOLDS.items():
            gate = gates.get(gate_name, {})
            if not isinstance(gate, dict):
                reasons.append(f"{gate_name} gate is missing")
                continue
            if not bool(gate.get("passed", False)):
                reasons.append(f"{gate_name} gate is blocked")
            if int(gate.get("score", 0)) < int(gate.get("threshold", gate_threshold)):
                reasons.append(f"{gate_name} score is below threshold")
        if not isinstance(total, int):
            reasons.append("plan_score.total must be an integer")
        elif total < effective_threshold:
            reasons.append(f"Plan score {total} is below threshold {effective_threshold}")
        if decision not in {"approved", "pass", "passed"}:
            reasons.append(f"Plan decision is not approved: {decision or 'missing'}")
        if not isinstance(hard_blockers, list):
            reasons.append("plan_score.hard_blockers must be an array")
        elif hard_blockers:
            reasons.append("Hard blockers exist: " + "; ".join(str(item) for item in hard_blockers))
    if isinstance(goal_spec, dict) and not bool(goal_spec.get("user_confirmation", False)):
        reasons.append("GoalSpec user_confirmation is missing or false")
    return not reasons, reasons


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the codex-claude-ralph Plan Gate.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--threshold", type=int, default=THRESHOLD)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    score = read_json(repo / ".codex-ralph" / "plan_score.json")
    goal_spec = read_json(repo / ".codex-ralph" / "goal_spec.json")
    approved, reasons = evaluate(score, goal_spec, args.threshold)
    payload = {
        "approved": approved,
        "threshold": args.threshold,
        "total": score.get("total") if isinstance(score, dict) else None,
        "decision": score.get("decision") if isinstance(score, dict) else None,
        "hard_blockers": score.get("hard_blockers", []) if isinstance(score, dict) else [],
        "gates": score.get("gates", {}) if isinstance(score, dict) else {},
        "reasons": reasons,
        "goal_spec_path": str(repo / ".codex-ralph" / "goal_spec.json"),
        "plan_score_path": str(repo / ".codex-ralph" / "plan_score.json"),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("Plan gate approved." if approved else "Plan gate blocked: " + " | ".join(reasons))
    if not approved:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
