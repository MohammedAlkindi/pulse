"""Build the Markdown weekly briefing from analysis + raw event counts."""

from datetime import datetime, timezone


def _bullet_list(items: list[str], fallback: str = "_None identified._") -> str:
    if not items:
        return fallback
    return "\n".join(f"- {item}" for item in items)


def generate(
    week: str,
    analysis: dict,
    event_counts: dict[str, int],
) -> str:
    """
    Assemble the briefing Markdown.

    event_counts: {source: count} as returned by db.count_events_for_week()
    analysis: structured dict from analyzer.analyze()
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    gmail_received = event_counts.get("gmail_received", 0)
    gmail_sent = event_counts.get("gmail_sent", 0)
    github_total = event_counts.get("github", 0)
    notion_total = event_counts.get("notion", 0)

    themes = _bullet_list(analysis.get("themes", []))
    active = _bullet_list(analysis.get("active_projects", []))
    drifting = _bullet_list(analysis.get("drifting", []))
    next_week = _bullet_list(analysis.get("attention_next_week", []))
    dq_notes = analysis.get("data_quality_notes", [])

    dq_section = ""
    if dq_notes:
        dq_section = "\n## Data Quality Notes\n" + _bullet_list(dq_notes) + "\n"

    briefing = f"""\
# Weekly Pulse — {week}
_Generated {today} · Review before acting on any item_

## What Happened

### Active Projects
{active}

### Themes
{themes}

## Activity

| Source | Detail | Count |
|--------|--------|-------|
| Gmail | Received | {gmail_received} |
| Gmail | Sent | {gmail_sent} |
| GitHub | Events | {github_total} |
| Notion | Pages | {notion_total} |

## Drifting

{drifting}

## Next Week

{next_week}
{dq_section}"""
    return briefing
