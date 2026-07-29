"""Build the Markdown weekly briefing from analysis + raw event counts."""

from datetime import datetime, timezone

_TREND_MARKS = {"rising": "↑", "steady": "→", "falling": "↓", "stalled": "■", "new": "✦"}


def _bullet_list(items: list[str], fallback: str = "_None identified._") -> str:
    if not items:
        return fallback
    return "\n".join(f"- {item}" for item in items)


def _momentum_section(momentum: dict | None) -> str:
    tracks = (momentum or {}).get("tracks", [])
    if not tracks:
        return ""
    rows = "\n".join(
        f"| {_TREND_MARKS.get(t['trend'], '?')} {t['trend']} | {t['source']}/{t['key']} "
        f"| {t['this_week']} | {t['prior_avg']} |"
        for t in tracks[:12]
    )
    return f"""
## Momentum
_Computed from {len(momentum['weeks'])} weeks of stored history — not model output._

| Trend | Track | This week | Prior avg |
|-------|-------|-----------|-----------|
{rows}
"""


def generate(
    week: str,
    analysis: dict,
    event_counts: dict[str, dict[str, int]],
    momentum: dict | None = None,
) -> str:
    """
    Assemble the briefing Markdown.

    event_counts: {source: {event_type: count}} as returned by
    db.count_events_by_type_for_week() — the per-type split is what lets
    Gmail report received vs sent instead of a single opaque total.
    analysis: structured dict from analyzer.analyze()
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    gmail = event_counts.get("gmail", {})
    gmail_received = gmail.get("email_received", 0)
    gmail_sent = gmail.get("email_sent", 0)
    github_total = sum(event_counts.get("github", {}).values())
    notion_total = sum(event_counts.get("notion", {}).values())

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
{_momentum_section(momentum)}
## Drifting

{drifting}

## Next Week

{next_week}
{dq_section}"""
    return briefing
