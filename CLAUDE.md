# Pulse — project context for Claude Code

> Project-specific context layered on top of the global standards in `~/.claude/CLAUDE.md`.

## What it does
Personal intelligence agent. Ingests activity from Gmail, GitHub, and Notion
into local SQLite, computes week-over-week momentum per track (repo / page /
sender domain), has Claude analyze the week grounded in that momentum, and
emails a weekly Markdown briefing. Local-first: no server, no cloud storage.

## Stack
Python 3.13, SQLite, Anthropic SDK (`claude-opus-5` default), Google API
client (Gmail OAuth), Notion REST, pytest. Windows Task Scheduler for the
weekly run.

## Commands
```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest                                                        # must pass before any commit
python agent/run_pulse.py --config config/pulse_config.yaml   # full run (add --send to email)
```

## Conventions
- Conventional commits, one logical change each; secrets never hardcoded;
  external API calls via the source/analyzer service layers; source failures
  are logged and skipped, never raised.
- Deterministic logic (momentum, counting, trimming, rendering) lives in pure
  functions with unit tests; I/O stays in sources, store, and emailer.
- Never store email or page bodies — subjects, titles, and bounded snippets only.
- Momentum lines in the prompt are computed facts; the analyzer must ground
  "drifting" in them, not invent trends.
