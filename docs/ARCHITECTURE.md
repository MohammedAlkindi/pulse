# Architecture

Pulse reconstructs a week of work as connected workstreams with evidence
behind every claim. Local-first: source data, derived history, and briefings
never leave the machine.

## Pipeline

```
  Gmail          GitHub          Notion
    │               │               │        incremental, cursor-based,
    └───────────────┼───────────────┘        idempotent, per-source isolated
                    ▼
         ┌─────────────────────┐
         │  canonical ledger   │  events: id, source, type, actor, title,
         │  (SQLite + FTS5)    │  url, content hash, revision, sensitivity,
         └──────────┬──────────┘  tombstone, week, workstream
                    ▼
         ┌─────────────────────┐
         │ workstream resolver │  deterministic rules; ambiguity → review queue
         └──────────┬──────────┘
                    ▼
    ┌───────────────┼────────────────┐
    ▼               ▼                ▼
 momentum      extraction        items ledger      all deterministic,
 (5-week       (decisions,       (durable,         all evidence-linked
  trends)       commitments,      append-only
                blockers,         history)
                deadlines)
    └───────────────┼────────────────┘
                    ▼
         ┌─────────────────────┐
         │  analyzer (Claude)  │  optional; cited entries only, validated
         └──────────┬──────────┘
                    ▼
         ┌─────────────────────┐
         │ briefing generator  │  citation registry drops any unresolvable claim
         └──────────┬──────────┘
                    ▼
         Markdown briefing · local web UI · Ask Pulse
```

Nothing above the analyzer requires an API key. Without one, Pulse still
produces a complete evidence-backed operating review — the model adds
interpretation, not facts.

## Schema

```sql
events(                       -- the canonical ledger
  id PK, source, event_type, title, metadata JSON,
  occurred_at, ingested_at, week_number,        -- UTC; ISO week keys
  actor, canonical_url, content_hash,           -- provenance
  source_updated_at, sensitivity, deleted,      -- revision + trust + tombstone
  workstream_id)
events_fts(event_id, title, snippet)            -- FTS5 index

sync_state(source PK, cursor_ts, last_success_at, last_status, last_error)

workstreams(id PK, name, kind, status, created_at)
workstream_members(member_type, member_key PK, workstream_id, origin)
link_suggestions(id PK, workstream_id, member_type, member_key,
                 evidence JSON, confidence, status, created_at)

items(id PK, kind, text, workstream_id, counterparty, due_date, status,
      evidence JSON, confidence JSON, trust, first_week, last_week, ...)
item_history(seq PK, item_id, week, change, detail, evidence JSON, created_at)

briefings(id PK, week_number, generated_at, delivered, content)
schema_version(version PK, name, applied_at)
```

Migrations are versioned and forward-only. A database created before
versioning is detected by the presence of `events` and recorded at
version 1 rather than having the baseline replayed over real history.

## Design rules

**Sync is incremental and idempotent.** Each source stores a cursor;
the next run starts two days before it (capped at thirty days of
catch-up) so a machine that was off does not lose the gap. Re-ingesting
the same range creates zero duplicates: writes are content-hash upserts
that update changed records in place and preserve `ingested_at`.

**Workstream resolution is deterministic first.** Repositories, Notion
databases, and standalone pages anchor their own workstreams; a
user-declared initiative absorbs a repo or page of the same name so one
workstream spans all three sources. Email joins by previously linked
thread, configured sender domain, whole-word alias, or an explicit repo
URL. One strong match links the thread durably; multiple matches go to
`link_suggestions` and the event stays unassigned. Model guesses are
never promoted to ground truth silently.

**Confidence is derived, not self-reported.** `high` means two or more
events or corroboration across two sources; `medium` a single recent
event; `low` anything thinner. Trust is a separate axis: content that
attempts instruction injection is marked `suspicious` and rendered with
an explicit warning, external senders as `external`. Trust never
downgrades.

**Citations are enforced structurally.** Every briefing line renders
through a registry that resolves markers against the run's real evidence
context — ledger events plus computed momentum keys. A claim whose
citations do not resolve is dropped and logged. A briefing physically
cannot cite evidence Pulse does not hold.

**Source text is data, never instructions.** Content is sanitized at both
boundaries: prompt framing (tag-like sequences and directive phrases
removed, so text cannot forge context boundaries or evidence ids) and
Markdown rendering (HTML, dangerous links, control characters, table
pipes). The model's own output is then citation-validated, which is the
backstop if prompting fails.

**Partial failure degrades, never corrupts.** A source that fails is
recorded in `sync_state` with its cursor preserved for resume; other
sources keep their data, and the briefing discloses what was missing.

## Time handling

All timestamps are stored as UTC ISO-8601. Weeks are ISO week keys
(`YYYY-WNN`) computed from `isocalendar()`, so the ISO year is used —
2024-12-30 belongs to `2025-W01`. Deadline phrases resolve relative to
when they were said, not when the briefing runs.

## Local data locations

| Path | Contents |
|---|---|
| `data/pulse.db` | The ledger: events, workstreams, items, history, briefings |
| `data/demo/` | Synthetic demo database and briefing (never touches real data) |
| `logs/briefing_draft.md` | Latest generated briefing |
| `logs/manifest.jsonl` | Append-only run audit trail |
| `config/pulse_config.yaml` | Your config (gitignored) |
| `config/credentials.json`, `config/token.json` | Gmail OAuth (gitignored) |

Credentials are never written to any of the above except the two OAuth
files Google requires on disk.
