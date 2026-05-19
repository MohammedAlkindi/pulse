# Pulse

Personal intelligence agent. Ingests activity from Gmail, GitHub, and Notion,
analyses patterns with Claude, and delivers a weekly Markdown briefing.

Runs entirely locally. No server. No cloud storage. SQLite only.

---

## What Pulse Does

1. **Ingests** — fetches the last 7 days of activity from your connected sources.
2. **Stores** — writes normalised events to a local SQLite database (`data/pulse.db`).
3. **Analyses** — sends event summaries (never body content) to Claude to identify themes, active projects, drifting areas, and next-week priorities.
4. **Briefs** — generates a Markdown briefing and writes it to `logs/briefing_draft.md`.
5. **Delivers** — optionally sends the briefing via Gmail when `--send` is passed.

---

## What Is Never Stored

- Email body content (only subject + 120-char snippet)
- Notion page body (only title, status, last-edited time)
- Any credential or token (gitignored)

---

## Setup

### 1. Clone and install dependencies

```powershell
cd C:\Users\you\projects\Pulse
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Copy and edit the config

```powershell
copy config\pulse_config.example.yaml config\pulse_config.yaml
```

Fill in `pulse_config.yaml`:
- `sources.github.username` — your GitHub username
- `briefing.recipient_email` / `briefing.sender_email` — email addresses

### 3. Set environment variables

| Variable | Required for | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Analysis | Anthropic API key |
| `GITHUB_TOKEN` | GitHub source | Personal Access Token with `read:user` and `public_repo` |
| `NOTION_TOKEN` | Notion source | Notion integration token |

Set them in your shell profile or via Windows Environment Variables settings.

### 4. Gmail OAuth

Gmail uses OAuth 2.0 with a Google Cloud project.

1. Create a project at [console.cloud.google.com](https://console.cloud.google.com).
2. Enable the **Gmail API**.
3. Create an **OAuth 2.0 Desktop App** credential.
4. Download the credentials JSON and save it to `config/credentials.json`.
5. On first run, a browser window will open for you to authorise access.
   The token is saved to `config/token.json` automatically.

### 5. Notion Integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations).
2. Create an integration and copy the **Internal Integration Token**.
3. Set it as `NOTION_TOKEN` in your environment.
4. In Notion, open each workspace or database you want to track and click
   **Share → Invite** to give the integration access.

---

## Running Manually

```powershell
# Ingest only — no analysis, no briefing
python agent/run_pulse.py --config config/pulse_config.yaml --dry-run

# Full run — ingest + analyse + generate briefing (no email)
python agent/run_pulse.py --config config/pulse_config.yaml

# Full run + deliver briefing via email
python agent/run_pulse.py --config config/pulse_config.yaml --send
```

The briefing is always written to `logs/briefing_draft.md` before any email is sent.

---

## Scheduling with Task Scheduler

From an elevated PowerShell session:

```powershell
.\setup_scheduler.ps1 `
  -PythonPath "C:\Users\you\projects\Pulse\.venv\Scripts\python.exe" `
  -ProjectRoot "C:\Users\you\projects\Pulse"
```

This registers a task that runs every Sunday at 6:00 PM with `--send`.
Adjust `-Hour` and `-Minute` parameters to change the time.

---

## Project Structure

```
pulse/
├── agent/
│   ├── run_pulse.py          ← CLI entry point
│   ├── config.py             ← YAML config loader
│   ├── paths.py              ← path resolution
│   ├── scheduler.py          ← orchestration
│   ├── manifest.py           ← run audit trail (logs/manifest.jsonl)
│   ├── retry.py              ← exponential backoff decorator
│   ├── sources/
│   │   ├── gmail.py          ← Gmail ingestion
│   │   ├── github.py         ← GitHub activity
│   │   └── notion.py         ← Notion pages
│   ├── store/
│   │   ├── db.py             ← SQLite CRUD
│   │   └── models.py         ← Event / Briefing dataclasses
│   ├── analysis/
│   │   └── analyzer.py       ← Claude API analysis
│   └── briefing/
│       ├── generator.py      ← Markdown builder
│       └── emailer.py        ← Gmail delivery
├── config/
│   └── pulse_config.example.yaml
├── templates/
│   └── briefing_prompt.md    ← Documents the Claude system prompt
├── logs/                     ← gitignored; briefings and manifest live here
├── data/                     ← gitignored; pulse.db lives here
├── requirements.txt
├── setup_scheduler.ps1
└── README.md
```

---

## Adding a New Source

1. Create `agent/sources/mysource.py` with a `fetch(cfg: Config) -> list[Event]` function.
2. Add a `mysource:` block to `pulse_config.example.yaml` (and your local config).
3. Call `cfg.source_enabled("mysource")` and `_ingest_source("mysource", cfg)` in `scheduler.py`.
4. Handle all failures inside `fetch()` — log and return `[]`, never raise.

---

## Data Schema

### `events` table

| Column | Type | Description |
|---|---|---|
| id | TEXT PK | `{source}:{source_id}` |
| source | TEXT | `gmail` / `github` / `notion` |
| event_type | TEXT | e.g. `email_received`, `commit`, `page_updated` |
| title | TEXT | Subject, commit message, page title |
| metadata | TEXT | JSON; source-specific fields |
| occurred_at | TEXT | ISO 8601 UTC |
| ingested_at | TEXT | ISO 8601 UTC |
| week_number | TEXT | `YYYY-WNN` |

### `briefings` table

| Column | Type | Description |
|---|---|---|
| id | TEXT PK | UUID |
| week_number | TEXT | `YYYY-WNN` |
| generated_at | TEXT | ISO 8601 UTC |
| delivered | INTEGER | 0 / 1 |
| content | TEXT | Full Markdown |

---

## Credentials Checklist

| File / Variable | Location | Gitignored? |
|---|---|---|
| `config/credentials.json` | Google Cloud OAuth client | Yes |
| `config/token.json` | Auto-generated on first Gmail auth | Yes |
| `config/pulse_config.yaml` | Your local config | Yes |
| `ANTHROPIC_API_KEY` | Env var | N/A |
| `GITHUB_TOKEN` | Env var | N/A |
| `NOTION_TOKEN` | Env var | N/A |
