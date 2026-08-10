# AGENTS.md — Pulse

Read this and `CLAUDE.md` before working here. Full standards: `~/.claude/CLAUDE.md` and `~/Github/CLAUDE.md`.

## Scope
Implement features, fix bugs, and refactor within this repo.

## Branch & commits
Global — see `~/.claude/CLAUDE.md` for commit format, sizing, attribution and the
branch/push table. This repo adds no exceptions.

## Requires explicit confirmation
Destructive git ops (force-push, history rewrite), deploying anything to a
network-reachable host, adding a cloud dependency that would hold personal
data, changing secret handling, and data deletion beyond `--purge`.

## Before done
- `pytest` passes in full (hermetic — no network, no credentials).
- New capability ⇒ ground truth in `agent/demo/corpus.py` and a measuring
  test in `tests/test_eval_corpus.py`.
- `python agent/run_pulse.py --demo` still produces a briefing end-to-end.
- No secret, token, or real user data added to the repository or fixtures.
