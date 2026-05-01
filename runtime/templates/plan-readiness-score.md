# Plan Readiness Score Template

Use this template when Codex prepares `<repo>/.codex-ralph/plan_score.json`.

Required fields:

- `total`
- `decision`
- `threshold`
- `discussion_ready`
- `hard_blockers`
- `dimensions`
- `gates`

Fixed gate:

- `discussion_ready` must be `true`
- `open_questions` must be empty
- `missing_decisions` must be empty
- threshold = `85`
- non-empty `hard_blockers` blocks execution
- `decision` must be `approved`, `pass`, or `passed`
- user confirmation must still be checked separately in GoalSpec

Required gates:

- `epistemic`
- `deontic`
- `dialectical`

Required gate thresholds:

- `epistemic >= 70`
- `deontic >= 70`
- `dialectical >= 60`

Required dimensions:

- epistemic:
  - `intent_clarity`
  - `outcome_clarity`
  - `scope_clarity`
  - `constraints_clarity`
  - `success_criteria_clarity`
  - `codebase_grounding`
- deontic:
  - `allowed_scope_explicitness`
  - `forbidden_scope_explicitness`
  - `non_goals_explicitness`
  - `decision_boundaries_explicitness`
  - `approval_boundary_clarity`
- dialectical:
  - `pressure_pass_completed`
  - `alternatives_examined`
  - `contradiction_check`
  - `failure_mode_coverage`

Rules:

- if discussion is not ready, `total` must not exceed `84`
- if any gate is blocked, overall `decision` must be `blocked`
- scorecard output is the primary readiness view, not a single scalar summary
