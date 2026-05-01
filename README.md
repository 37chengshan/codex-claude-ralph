# codex-claude-ralph

`codex-claude-ralph` is a Codex workflow skill for running a Ralph-style agent loop without handing control of the whole Codex session to a separate platform.

The policy is intentionally narrow:

- **Codex** stays in the current conversation as planner, scheduler, reviewer, merge controller, and final judge.
- **Claude CLI** is the only worker and runs in visible macOS Terminal windows.
- **Ralph runtime** owns state files, worktrees, events, artifacts, worker launch commands, merge bookkeeping, and status export.
- **Playwright** is required evidence for browser, canvas, 3D, visualization, and interaction tasks.

This is not an `oh-my-codex` replacement and it does not globally take over Codex. It activates only when the user explicitly invokes `$codex-claude-ralph`, `/use codex-claude-ralph`, or asks for the Codex-to-Claude Ralph workflow.

![Model economics](assets/ralph-model-economics.svg)

## Why

The point of this workflow is not to spend the strongest model on every token. The point is to spend a small premium-model budget on decomposition, supervision, review, and repair decisions, then push the bulk implementation work into a cheaper worker lane.

- **Best worker quality bar:** `Claude Sonnet 4.6`
- **Low-cost worker direction:** Claude can be paired with cheaper execution models such as `MiniMax-2.7-HighSpeed` for high-volume implementation passes
- **Operating thesis:** premium oversight plus low-cost execution can approach premium-only shipped quality when the review loop is strict

If absolute worker quality matters more than cost, use `Claude Sonnet 4.6` as the worker. Ralph exists for the opposite case: keep quality high while reducing expensive planning and implementation tokens.

![Codex Claude Ralph command loop](assets/ralph-codex-hero.svg)

## Workflow

Every run is a visible command loop inside the current Codex conversation.

1. The user gives a task, bug, feature, or repair target.
2. Codex explores the repository in read-only mode before asking codebase questions.
3. If the request is ambiguous, Codex enters an `oh-my-codex`-style interview: one high-leverage question per round.
4. Each discussion round shows the full readiness scorecard: `epistemic`, `deontic`, `dialectical`, total score, hard blockers, open questions, missing decisions, and why the current question matters.
5. Execution stays blocked until all gates pass, total score is at least `85`, and there are no hard blockers.
6. Codex creates and shows a task DAG with dependencies, write scopes, validation commands, Playwright requirements, and parallel batches.
7. The user confirms the task graph once before any worker starts.
8. Ralph creates one git worktree and branch per task.
9. Ralph opens Claude CLI in visible Terminal windows and records logs and artifacts under `.codex-ralph/`.
10. Codex reads worker output, diffs, tests, and Playwright evidence in the current conversation.
11. Codex either approves the task, writes a concrete rework brief, or blocks the run.
12. Each task gets at most three automatic Claude rework attempts.
13. After the rework limit, the user chooses whether to continue Claude rework or let the current Codex/GPT session take over.
14. Approved task branches merge into the integration branch.
15. Codex performs a final full review before the run can complete.

![Workflow DAG and review loop](assets/ralph-codex-flowchart.svg)

## Installation

Install globally:

```bash
./install/install.sh global
```

Install into a project:

```bash
./install/install.sh project --repo /absolute/path/to/repo
```

Check the installation:

```bash
./install/doctor.sh --repo /absolute/path/to/repo
```

## Commands

Discussion and status:

```bash
runtime/ralph.sh status --repo /absolute/path/to/repo --json
runtime/ralph.sh answer --repo /absolute/path/to/repo --choice A --note "..." --language en
```

Task graph and worker execution:

```bash
runtime/ralph.sh plan --repo /absolute/path/to/repo --task-graph /path/to/task_graph.json
runtime/ralph.sh launch --repo /absolute/path/to/repo --task-id T1 --run-id run-id --visible-terminal
runtime/ralph.sh collect --repo /absolute/path/to/repo --task-id T1 --run-id run-id
```

Review, merge, and handoff:

```bash
runtime/ralph.sh review-mark --repo /absolute/path/to/repo --task-id T1 --verdict passed --review /path/to/review.json
runtime/ralph.sh merge --repo /absolute/path/to/repo --task-id T1 --run-id run-id
runtime/ralph.sh handoff --repo /absolute/path/to/repo --mode continue_claude_rework
runtime/ralph.sh handoff --repo /absolute/path/to/repo --mode codex_takeover
```

Playwright smoke verification:

```bash
runtime/ralph.sh playwright --repo /absolute/path/to/repo --task-id T1 --url http://127.0.0.1:3000
```

Legacy compatibility entrypoint:

```bash
runtime/scripts/ralph-skill-run.sh --repo /absolute/path/to/repo --goal-spec /absolute/path/to/repo/.codex-ralph/goal_spec.json --max-steps 5
```

## Files

All workflow state and communication files live in the target repository under `.codex-ralph/`:

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

`status --json` exposes:

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

## Review Policy

Claude success output is not acceptance. Codex must review deterministic evidence before a task is marked passed.

The fixed review dimensions are:

- `requirements_fit`
- `acceptance_coverage`
- `scope_compliance`
- `verification_evidence`
- `integration_risk`
- `ux_or_runtime_quality`

Browser, frontend, canvas, 3D, visualization, and interaction tasks are blocked without Playwright evidence.

## Skill Display

Codex Desktop may render skills as `{package}:{display_name}`. The package remains `codex-claude-ralph`, but the UI display name is `Workflow`, avoiding the repeated label `Codex Claude Ralph: Codex Claude Ralph`.

The trigger remains unchanged:

```text
$codex-claude-ralph
/use codex-claude-ralph
```

## Verification

The automated test suite covers:

- global and project install
- doctor checks
- status and answer compatibility
- task graph planning and status export
- visible Terminal launch command generation
- git worktree creation
- collect, review-mark, merge, and handoff
- Playwright spec generation
- worker adapter success, blocked, invalid JSON, timeout, and non-zero exit
- hook configuration validation
