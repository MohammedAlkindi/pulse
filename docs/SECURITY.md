# Security & privacy

## Threat model

Pulse ingests content written by other people and feeds a language model.
The assumptions that follow from that:

| Threat | Mitigation | Residual risk |
|---|---|---|
| **Prompt injection** — an email instructs the model to hide risks or invent commitments | Extraction is deterministic pattern matching, not model instruction-following. Source text is sanitized before entering any prompt (tag-like framing and directive phrases stripped) and wrapped in delimited blocks declared untrusted. Model output is citation-validated. Items from hostile content are marked `suspicious` and rendered with an explicit UNVERIFIED warning. | A model with a key configured could still be nudged in phrasing. It cannot introduce evidence, and its uncited claims are dropped. |
| **Evidence fabrication** — a claim referencing something that never happened | Every briefing line renders through a citation registry validated against the run's real evidence set; unresolvable claims are dropped and logged. | A correctly-cited event can still be misinterpreted; that is why interpretation is labeled. |
| **Credential exposure** | Credentials come from environment variables or the OS keychain, never the database, briefing, manifest, or logs. A redaction chokepoint scrubs token shapes and known values from every diagnostic path before storage. The UI shows a masked tail only. | OAuth tokens must exist on disk (`config/token.json`) because Google's client requires it. Both are gitignored. |
| **Data exfiltration via the UI** | The server binds to `127.0.0.1` and refuses other hosts, serves only files inside its static directory, and sends a strict CSP with no inline script. | Anyone with local access to the machine can read the database — it is unencrypted SQLite by design. Use full-disk encryption. |
| **XSS from source content** | Values are sanitized server-side and escaped client-side before rendering. | — |
| **Accidental data loss** | Ingestion is transactional and idempotent; migrations are versioned with pre-versioning detection. | `--purge` is irreversible by design. Export first. |

## What leaves the machine

Nothing, unless you configure an Anthropic API key. With one configured,
the analysis step sends event **titles and short snippets** (never message
bodies, never full pages) plus computed momentum lines to the Anthropic
API. Ask Pulse sends retrieved records for the question asked, bounded by
both record count and bytes. Everything else — the ledger, items,
briefings, history — stays local.

Without a key, Pulse still produces a full evidence-backed briefing. The
model adds interpretation, not facts.

## What is never stored

- Email bodies (subject plus a 120-character snippet only)
- Notion page bodies (title, status, last-edited time only)
- Any credential, in any table, log, or briefing

## Reporting

This is a personal project without a formal disclosure process. Open an
issue for anything that does not involve a live credential; for anything
that does, contact the maintainer directly.
