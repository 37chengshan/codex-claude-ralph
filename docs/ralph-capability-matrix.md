# Ralph Capability Matrix

This repository targets **Ralph source-repo compatibility with a Codex-only command layer**.

## Scope Boundary

- Goal: look and feel like the original Ralph source repo while using Codex as the only commander
- Worker runtime: Claude Code only
- Explicit non-goal: Amp runtime support
- Explicit non-goal: `dev-browser` façade compatibility

## Capability Matrix

| Capability | Original Ralph | This Fork |
| --- | --- | --- |
| Root source-repo layout | Yes | Yes |
| `ralph.sh` primary entrypoint | Yes | Yes |
| Root `prd.json` / `progress.txt` | Yes | Yes |
| Fresh-context single-story loop | Yes | Yes |
| `branchName`-driven branch workflow | Yes | Yes |
| Auto commit per passing story | Yes | Yes |
| Amp worker backend | Yes | No |
| Claude worker backend | Yes | Yes |
| Root Ralph-compatible `prd.json` export | Native | Yes |
| Hidden richer internal state | Limited / implicit | Yes, `.codex-ralph/state.json` |
| Explicit doctor / lock / timeout / archive | Partial | Yes |
| Browser verification | Yes | Yes, via direct browser verifier |
| `dev-browser` façade | Yes | No |
| Public-vs-private state split | No strong boundary | Yes |

## Public vs Private State

Public root files stay human-facing and Ralph-compatible:

- `prd.json`
- `progress.txt`
- `prompt.md`
- `CLAUDE.md`

Private runtime files stay under `.codex-ralph/`:

- `config.json`
- `state.json`
- `runs/`
- `archive/`

The runtime imports root `prd.json` into canonical state before each run, executes the loop, then exports back to root `prd.json`.

## Browser Verification Policy

This fork exposes browser verification directly instead of preserving the original `dev-browser` naming. The reason is architectural: the command layer is Codex-only, so the original Claude skill façade is not a natural fit.

Behavior:

- Non-UI story: no browser verification required
- UI story + verifier configured + verifier passes: story may pass
- UI story + verifier configured + verifier fails: blocked
- UI story + verifier missing: blocked
