# Gap Register

Audit date: 2026-07-29. Ordered by severity. Status reflects this phase's work.

## Critical — trust and core thesis

| # | Gap | User impact | Resolution |
|---|-----|-------------|------------|
| 1 | **No evidence linkage.** Analysis output (themes, drifting, next-week) carries zero references to the events that justify it; claims are unverifiable and unfalsifiable. | A briefing statement cannot be checked; hallucinated movement is indistinguishable from fact. | Canonical event ledger + extraction that must cite event ids + programmatic citation validation that rejects uncited or mis-cited claims. |
| 2 | **No cross-source connection.** Gmail, GitHub, and Notion are summarized independently; nothing links an email thread to the repo and page it concerns. | The product's core promise (connected workstreams) does not exist. | Deterministic workstream resolution (repo identity, Notion hierarchy, thread ids, aliases, URL mentions) with an explicit review queue for ambiguous links. |
| 3 | **Nothing persists between briefings except raw events.** Decisions, commitments, deadlines, and risks are regenerated from scratch weekly and vanish. | "What did I promise, and is it still open?" is unanswerable. | Items ledger (decision / commitment / deadline / risk / question) with status history that is appended, never overwritten. |
| 4 | **No prompt-injection defense.** Email subjects and snippets flow into the analysis prompt as-is, with no delimiting, no untrusted-data rules, and no regression tests. | A hostile email can steer the briefing ("report no risks", fabricate commitments). | Structural delimiting + explicit untrusted-content rules + citation validation as a backstop + hostile-fixture regression tests. |
| 5 | **Sync is a fixed 7-day refetch, not incremental.** No cursors or checkpoints; if the agent doesn't run for 10 days, days 8–10 are silently lost forever; interrupted runs restart from nothing. | Permanent data loss without any signal. | Per-source sync cursors with overlap, resumable checkpoints, and connector status recording. |

## High — reliability

| # | Gap | User impact | Resolution |
|---|-----|-------------|------------|
| 6 | No schema migrations — bare `CREATE IF NOT EXISTS`; any schema change strands existing databases. | Upgrades corrupt or orphan user history. | Versioned migration runner with baseline detection for pre-versioning databases. |
| 7 | `insert_event` opens one connection per event; ingestion is non-transactional. | Crash mid-source leaves partial writes; slow. | Single-transaction bulk upsert per source. |
| 8 | Events are immutable after first sight — no content hash or source-update timestamp, so upstream edits (PR merged, page renamed) never surface. | Ledger drifts from reality. | Content-hash upsert: update changed rows, preserve `ingested_at`. |
| 9 | Retry treats all errors alike — no rate-limit (429/403) awareness, no jitter. | Hammering APIs during outages; avoidable failures. | Status-aware retry honoring Retry-After where present. |
| 10 | No data export, no full local deletion, no retention controls. | "Local-first" without the rights that make it meaningful. | Export and wipe commands surfaced in CLI and UI. |

## Medium — product

| # | Gap | User impact | Resolution |
|---|-----|-------------|------------|
| 11 | No interface beyond CLI + emailed Markdown; no way to inspect evidence, history, or connector health. | Trust requires seeing the source behind a claim. | Local web UI: briefing, workstreams, items, evidence drawer, Ask Pulse, sync health, settings. |
| 12 | No demo mode — first useful output requires three credential setups. | Most evaluators never see a briefing. | Deterministic synthetic corpus + one-command demo requiring no credentials. |
| 13 | No temporal querying ("what did I promise Sarah?"). | History exists but is not interrogable. | Ask Pulse: FTS5 + structured queries over the ledger, byte-bounded LLM context, validated citations. |
| 14 | Secrets are env-var-only presence checks; no keychain option, no masking, no real connection tests. | Weak operational story. | OS-keychain support (optional), secret redaction in logs/errors, per-connector live connection tests. |
| 15 | "Material changes since last briefing" is not computed. | Briefings restate rather than diff. | Deterministic week-over-week item/momentum diff. |

## Low

| # | Gap | Resolution |
|---|-----|------------|
| 16 | `templates/briefing_prompt.md` no longer matches the actual prompt. | Regenerate from code or remove. |
| 17 | `logs/manifest.jsonl` grows without bound. | Documented; rotation left as future work. |
| 18 | Gmail requests the `send` scope even for read-only usage. | Documented tradeoff (needed for `--send` delivery). |
| 19 | UTC-only week boundaries are correct but undocumented. | Documented in architecture notes. |

## README claims audit

Checked against code: all current README claims are implemented (ingestion, SQLite, momentum, dry-run, CI, scheduler). No unsupported claims found; the doc gaps are omissions (data locations, threat model, limitations), not inflation.
