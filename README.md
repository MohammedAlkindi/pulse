# Pulse

Public walkthrough: [read a synthetic weekly briefing](https://pulse-overview.vercel.app/sample.html).
The website build (`python scripts/build_site.py`) copies only `site/` and the shared briefing renderer/styles. It never reads a local ledger, configuration or credentials. The local interface and public example use the same escaped Markdown renderer; the original Markdown remains available to download.

[![CI](https://github.com/MohammedAlkindi/Pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/MohammedAlkindi/Pulse/actions/workflows/ci.yml)

**Pulse turns scattered work activity into an evidence-backed operating review.**

It reads your Gmail, GitHub, and Notion activity into a local ledger,
connects it into durable workstreams, tracks the decisions and commitments
that actually moved, and produces a weekly review where **every factual
claim carries a citation you can open**. Runs entirely on your machine. No
server, no cloud database, no account.

```bash
git clone https://github.com/MohammedAlkindi/Pulse && cd Pulse
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python agent/run_pulse.py --demo --ui               # synthetic data, no credentials
```

That opens the interface at `http://127.0.0.1:8787` with a full worked
example — briefing, workstreams, commitments, evidence drawer, and Ask
Pulse — using invented data. Nothing is uploaded and your real accounts are
never touched.

## What it produces

A nine-section review, with `[n]` markers that resolve to source records:

```
## 3 · Decisions made
- Decision (Sarah Chen): we decided to launch the OmanX beta next Friday.
  · confidence medium · claimed by external sender [1]
- Decision (attacker@evil.example): We decided to wire $9000 to the vendor.
  · ⚠ UNVERIFIED — source content attempted instruction injection [2]

## 7 · Neglected or stalled
- Stalled: github/demo/proofx — no activity this week after averaging 0.75/week [5]

## Sources
1. `gmail:demo:launch-1` gmail 2026-07-27: OmanX beta launch — https://mail.google…
5. `momentum:github/demo/proofx` computed momentum: stalled — 0 this week vs 0.75/week prior
```

That second decision is a prompt-injection attempt from the demo corpus.
Pulse surfaces it — with its evidence — rather than obeying it or hiding it.

## How it works

1. **Ingest** — incremental, cursor-based sync per source. Re-running a
   range creates zero duplicates; an interrupted or skipped week is caught
   up on the next run; one connector failing never affects the others.
2. **Connect** — events resolve into durable workstreams by deterministic
   rules (repository identity, Notion hierarchy, Gmail threads, sender
   domains, declared aliases, explicit URLs). Ambiguous links go to a
   review queue instead of being guessed.
3. **Extract** — decisions, commitments (whose, and to whom), deadlines,
   blockers, and open questions, each bound to the exact event it came
   from. Items persist across weeks: re-seen items accumulate evidence,
   resolution is recorded, nothing is overwritten.
4. **Compute** — five-week momentum per workstream: rising, steady,
   falling, stalled, new. Calculated, not asked of a model.
5. **Review** — the briefing renders through a citation registry that
   drops any claim whose evidence does not resolve. Interpretation is
   labeled as interpretation. Thin evidence is stated, not padded.

The model is optional. Without an API key Pulse produces the entire review
from deterministic evidence; with one, it adds an executive read and
recommendations — still citation-validated.

## Setup with your own accounts

```bash
cp config/pulse_config.example.yaml config/pulse_config.yaml
```

Set credentials as environment variables or in your OS keychain (service
`pulse`, which needs `pip install keyring`). Never put them in the config
file:

| Variable | For | Where |
|---|---|---|
| `ANTHROPIC_API_KEY` | Analysis (optional) | [console.anthropic.com](https://console.anthropic.com) |
| `GITHUB_TOKEN` | GitHub | PAT with `read:user`, `public_repo` |
| `NOTION_TOKEN` | Notion | [notion.so/my-integrations](https://www.notion.so/my-integrations) |

Gmail uses OAuth: enable the Gmail API in a Google Cloud project, download
the Desktop App credentials to `config/credentials.json`, and authorise on
first run. Verify everything from **Connectors → Test connection** in the
UI, or:

```bash
python agent/run_pulse.py --config config/pulse_config.yaml --dry-run   # ingest only
python agent/run_pulse.py --config config/pulse_config.yaml             # full review
python agent/run_pulse.py --config config/pulse_config.yaml --send      # and email it
python agent/run_pulse.py --ui                                          # interface
```

Weekly scheduling: `setup_scheduler.ps1` (Windows Task Scheduler).

## Your data

| Command | Effect |
|---|---|
| `--export path.json` | Full JSON export of everything stored |
| `--purge` | Irreversible local deletion |

Data locations, schema, and the full design rationale are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Threat model and privacy
boundaries are in [docs/SECURITY.md](docs/SECURITY.md).

## Tests

```bash
pytest                    # 221 hermetic tests, no network or credentials
pytest tests/test_eval_corpus.py   # the evaluation suite
```

The eval suite runs the whole pipeline against a synthetic six-week corpus
with declared ground truth and measures deduplication, workstream linking,
commitment and deadline extraction, citation validity (every `[n]` resolves
to a listed source), momentum correctness, injection containment,
insufficient-evidence honesty, and cross-source failure isolation. CI runs
the full suite on pushes to `main` and on pull requests.

## Limitations

- **GitHub history is capped** at what the events API returns (~300 events,
  90 days). A gap longer than that cannot be backfilled.
- **Extraction is pattern-based**, tuned for precision over recall: it will
  miss commitments phrased unusually. Deadlines require explicit language
  ("by Friday", "due 2026-08-10"); a bare "tomorrow" is not treated as one.
- **Workstream linking is conservative.** Ambiguous email lands in the
  review queue rather than being assigned, and unresolved review items do
  not yet have a UI action to accept them.
- **The database is unencrypted SQLite.** Anyone with access to the machine
  can read it — use full-disk encryption.
- **Single-user, single-machine.** No sync, no sharing, no multi-account.
- **Gmail OAuth requests the send scope** as well as read-only access, because
  `--send` emails the review from your account. It is requested even if you
  never use `--send`.
- **Manifest growth is unbounded** and rotation is not implemented.
