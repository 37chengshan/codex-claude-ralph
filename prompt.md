# Example Prompt

Replace this file with your real project goal before running `./ralph.sh init`.

## Goal

Add a small, verifiable feature to an existing application without changing unrelated areas.

## Suggested Shape

1. Keep the work split into 2-4 dependency-aware stories.
2. Prefer one story per worker pass.
3. For UI work, use repo-local Playwright verification behind `npm run test:e2e`.
4. Keep docs updates explicit instead of burying them in implementation stories.

## Constraints

1. Preserve the target repository's existing design system and architecture.
2. Do not add broad refactors or dependency churn unless the story requires it.
3. If the target repo contains `AGENTS.md`, only update it when the story uncovers a durable convention or gotcha.
4. Prefer deterministic verification evidence over model self-reporting.

## Acceptance Focus

1. Each story should have a clear objective, acceptance criteria, and suggested tests.
2. UI stories should either pass browser verification or remain blocked.
3. The final public state should be exported back into root `prd.json` with accurate `passes` values.
