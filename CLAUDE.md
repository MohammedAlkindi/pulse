# Pulse — project context for Claude Code

> Project-specific context layered on top of the global standards in `~/.claude/CLAUDE.md`.

## What it does
Turns scattered Gmail, GitHub, and Notion activity into an evidence-backed
weekly operating review. Events land in a local SQLite ledger, resolve into
durable cross-source workstreams, and produce decisions, commitments,
deadlines, risks, and momentum — every claim citable to a source record.
Local-first: no server, no cloud database, no account.

## Stack
Python 3.13, SQLite (+FTS5), Anthropic SDK (`claude-opus-5`, optional),
Google API client (Gmail OAuth), Notion REST, stdlib HTTP server for the UI,
pytest. Windows Task Scheduler for weekly runs.

## Commands
```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest                                                        # must pass before any commit
python agent/run_pulse.py --demo --ui                         # synthetic demo + interface
python agent/run_pulse.py --config config/pulse_config.yaml   # real run (--send to email)
python agent/run_pulse.py --ui                                # interface only
```

## Layout
`sources/` → `store/` (ledger, migrations) → `graph/` (workstream resolution)
→ `analysis/` (momentum, extraction, items, citations, sanitize) →
`briefing/` → `web/` and `query/`. `demo/` holds the synthetic corpus.

## Invariants — do not regress these
- **Every factual briefing line must cite resolvable evidence.** The citation
  registry drops anything else. Never bypass it to "show more".
- **Deterministic before model.** Extraction, momentum, linking, and
  confidence are computed. The model adds interpretation and must stay
  citation-validated; its self-confidence is never used.
- **Source text is untrusted data.** Sanitize at both boundaries (prompt
  framing and Markdown). Hostile content is surfaced with a trust label,
  never obeyed and never silently dropped. Trust never downgrades.
- **Sync stays idempotent and resumable.** Re-ingesting a range must create
  zero duplicates; a failed source keeps its cursor and never affects others.
- **Secrets never reach the database, briefing, manifest, or logs.** Route
  every diagnostic through `secrets.redact`.
- **The UI binds to localhost only** and returns no secret values.
- **Tests stay hermetic** — no network, no credentials, no real user data.
  Add ground truth to `demo/corpus.py` when adding a capability, and an eval
  in `tests/test_eval_corpus.py` that measures it.
- **Console output stays ASCII** (Windows cp1252 crashes on arrows/middots).

## Conventions
Commit format, attribution and branch policy are global — see `~/.claude/CLAUDE.md`.
Nothing about them is specific to this repo.
