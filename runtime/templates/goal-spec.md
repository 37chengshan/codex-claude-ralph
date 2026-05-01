# GoalSpec Template

Use this template when Codex prepares `<repo>/.codex-ralph/goal_spec.json`.

Required fields:

- `project_name`
- `branch_name`
- `goal`
- `allowed_scope`
- `forbidden_scope`
- `codebase_evidence`
- `acceptance_criteria`
- `verification`
- `risks`
- `discussion_ready`
- `discussion_summary`
- `open_questions`
- `missing_decisions`
- `discussion`
- `user_confirmation`
- `plan_score`

Discussion object rules:

- `discussion.mode` must be `deep_interview`
- `discussion.round` tracks the current single-question round
- `discussion.status` must be `needs_discussion` or `ready`
- `discussion.task_archetype` must map to a fixed checklist
- `discussion.current_question` must contain exactly one question
- `discussion.history` stores answered rounds
- `discussion.resolved_decisions` stores locked choices

Rules:

- every `codebase_evidence` item must cite a real file and line range
- `allowed_scope` and `forbidden_scope` must be explicit
- `acceptance_criteria` must be testable
- `verification` must name concrete commands or deterministic checks
- ambiguous requests must keep `discussion_ready = false`
- unresolved questions belong in `open_questions`
- unmade product or implementation choices belong in `missing_decisions`
- while `discussion.current_question` exists, Codex must ask only that one question
