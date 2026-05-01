---
name: codex-claude-ralph
description: Use when the user invokes $codex-claude-ralph or /use codex-claude-ralph, or asks Codex to plan, dispatch, review, and rework implementation through visible Claude CLI workers.
---

# codex-claude-ralph

## Product Contract

This skill is a current-conversation Codex planner/reviewer workflow. Codex stays in the user-visible conversation as the operator, planner, scheduler, reviewer, merge controller, and final acceptance judge. Claude CLI is only a terminal worker.

The workflow is aligned with oh-my-codex style planning:

- one high-leverage discussion question per round
- explore repo facts before asking user questions
- show readiness through `epistemic`, `deontic`, and `dialectical` gates
- approve the task graph before execution
- loop through review and rework until clean or the rework limit is reached

## Trigger

Load this skill when the user uses:

- `$codex-claude-ralph`
- `/use codex-claude-ralph`
- `/codex-claude-ralph`
- any request to run the Codex -> Claude Ralph workflow

## Role Split

- User: gives the goal, answers discussion questions, approves the task graph, chooses handoff if rework limit is reached.
- Codex: explores, interviews, scores readiness, creates `GoalSpec`, creates task DAG, launches Claude, reads artifacts, reviews diffs/tests/Playwright, writes review verdicts, merges approved work, performs final review, reports to user.
- Ralph runtime: state files, task graph storage, worktree creation, visible terminal launch command, artifact paths, events, status API, merge/handoff bookkeeping.
- Claude CLI: edits code only inside assigned task worktree and returns JSON. Claude does not plan the whole project or communicate with the user.

## Workflow

1. Explore the target repo before asking codebase questions.
2. If intent is ambiguous, enter deep interview.
3. Ask exactly one question per discussion round.
4. Every discussion round must show the current full scorecard: overall, `epistemic`, `deontic`, `dialectical`, hard blockers, open questions, missing decisions, and why the current question matters.
5. Only proceed when scorecard passes: total `>=85`, all gates pass, no hard blockers.
6. Codex creates and shows `task_graph.json`: goal summary, acceptance criteria, non-goals, risks, task DAG, dependencies, writable scope, verification, Playwright requirement, and parallel batches.
7. User confirms the task graph once before execution.
8. Runtime creates one git worktree and branch per task. Non-git mode is experimental and serial only.
9. Runtime launches Claude through macOS `Terminal.app` when `--visible-terminal` is used, and still writes logs/artifacts under `.codex-ralph/`.
10. Codex reads worker output, diff, tests, and Playwright artifacts in the current conversation.
11. Codex writes `review.json` through `runtime/ralph.sh review-mark`.
12. If review is `rework`, Codex writes a concrete rework brief and relaunches Claude. Each task gets at most 3 automatic rework attempts.
13. On the 3rd failed rework, enter `handoff_decision`; user chooses `continue_claude_rework` or `codex_takeover`.
14. Approved tasks are merged by Codex through `runtime/ralph.sh merge`.
15. After all tasks merge, Codex performs final review. Final review failure creates targeted rework; success is the only path to `complete`.

## Stable Files

All state and communication lives in the target repo under `.codex-ralph/`:

```text
.codex-ralph/
  state.json
  events.jsonl
  goal_spec.json
  scorecard.json
  task_graph.json
  integration.json
  runs/<run_id>/tasks/<task_id>/
    task.json
    brief.md
    claude_prompt.md
    worker_output.json
    worker_raw.log
    diff.patch
    tests.json
    playwright.json
    review.json
    rework_brief.md
    rework_history.json
  worktrees/<run_id>/<task_id>/
  playwright/
    <task_id>.spec.ts
    final.spec.ts
    screenshots/
    traces/
```

## Runtime Commands

Stable commands:

```bash
install/install.sh global
install/install.sh project --repo <repo>
install/doctor.sh

runtime/ralph.sh status --repo <repo> --json
runtime/ralph.sh answer --repo <repo> --choice A --note "..." --language zh
runtime/ralph.sh plan --repo <repo> --task-graph <path>
runtime/ralph.sh launch --repo <repo> --task-id <id> --run-id <id> --visible-terminal
runtime/ralph.sh collect --repo <repo> --task-id <id> --run-id <id>
runtime/ralph.sh review-mark --repo <repo> --task-id <id> --verdict passed|rework|blocked|failed --review <path>
runtime/ralph.sh merge --repo <repo> --task-id <id> --run-id <id>
runtime/ralph.sh handoff --repo <repo> --mode continue_claude_rework|codex_takeover
runtime/ralph.sh playwright --repo <repo> --task-id <id> --url <url>
```

`status --json` must expose:

- `stage`
- `status`
- `message`
- `scorecard`
- `task_graph`
- `current_batch`
- `active_workers`
- `review_queue`
- `rework_summary`
- `handoff_options`
- `events_path`
- `next_action`

## Review Contract

Claude worker JSON:

```json
{
  "status": "success | blocked | failed",
  "summary": "short summary",
  "changed_files": ["path"],
  "tests_run": ["command"],
  "blockers": ["reason"],
  "notes_for_reviewer": ["detail"]
}
```

Codex review JSON:

```json
{
  "verdict": "passed | rework | blocked | failed",
  "scores": {
    "requirements_fit": 0,
    "acceptance_coverage": 0,
    "scope_compliance": 0,
    "verification_evidence": 0,
    "integration_risk": 0,
    "ux_or_runtime_quality": 0
  },
  "blocking_issues": ["issue"],
  "rework_instructions": ["instruction"],
  "approved_changed_files": ["path"]
}
```

Codex must not pass a task merely because Claude says success. Codex must compare the diff, tests, Playwright evidence, and acceptance criteria.

## Playwright Rule

Any task touching browser UI, frontend, canvas, 3D, visualization, or interaction requires Playwright evidence. Generate specs with `runtime/ralph.sh playwright`. Review must block UI tasks that lack Playwright evidence unless the user explicitly narrows verification.

## Reporting

User-facing reporting must happen in the current Codex conversation:

- discussion round: one question plus full scorecard
- task graph: DAG, dependencies, scope, verification, Playwright requirements
- Claude launch: task id, branch, worktree, Terminal command
- worker done: artifact paths, summary, tests
- Codex review: verdict, scores, blockers, rework instructions
- merge: result and next batch
- final review: acceptance checklist, Playwright evidence, residual risk
- handoff: `continue_claude_rework` or `codex_takeover`

Follow the user's current language. Chinese input requires Chinese output and no mixed-language template.

## Do Not

- Do not bypass discussion readiness.
- Do not ask more than one discussion question per round.
- Do not execute before the user approves the task graph.
- Do not run Claude as a hidden background-only worker when visible terminal mode is requested.
- Do not let Claude edit the main worktree directly in v10 git mode.
- Do not mark a task complete without Codex review.
- Do not mark the run complete without final review.
- Do not spawn a second Codex process to do review; review is done by the current conversation.
