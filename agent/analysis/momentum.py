"""Deterministic week-over-week momentum, computed from stored history.

The analyzer previously asked Claude what was "drifting" while showing it a
single week of events — a question the model had no data to answer. This
module computes the answer instead: per-track weekly counts over a trailing
window, classified into trends, which both the prompt and the briefing then
report as fact.

A "track" is the unit of attention:
  github → the repository
  notion → the page title
  gmail  → the counterparty domain
"""

import re
from datetime import datetime, timedelta

from agent.store.models import iso_week

WINDOW_WEEKS = 5          # current week + 4 weeks of history
MIN_TOTAL_EVENTS = 2      # tracks with fewer events across the window are noise

RISING_FACTOR = 1.5
FALLING_FACTOR = 0.5

_TREND_ORDER = {"stalled": 0, "falling": 1, "new": 2, "rising": 3, "steady": 4}


def trailing_weeks(now: datetime, n: int = WINDOW_WEEKS) -> list[str]:
    """Return the last n ISO week keys, oldest first, ending with now's week."""
    weeks = []
    for i in range(n - 1, -1, -1):
        weeks.append(iso_week(now - timedelta(weeks=i)))
    return weeks


def _domain_of(sender: str) -> str:
    match = re.search(r"@([\w.-]+)", sender or "")
    return match.group(1).lower() if match else "unknown"


def track_key(event: dict) -> str | None:
    source = event.get("source")
    meta = event.get("metadata") or {}
    if source == "github":
        return meta.get("repo") or None
    if source == "notion":
        return (event.get("title") or "").strip() or meta.get("page_id") or None
    if source == "gmail":
        return _domain_of(meta.get("sender", ""))
    return None


def classify(current: int, prior_counts: list[int]) -> str:
    prior_total = sum(prior_counts)
    prior_avg = prior_total / len(prior_counts) if prior_counts else 0.0
    if prior_total == 0:
        return "new" if current > 0 else "steady"
    if current == 0:
        return "stalled"
    if current > prior_avg * RISING_FACTOR:
        return "rising"
    if current < prior_avg * FALLING_FACTOR:
        return "falling"
    return "steady"


def compute_momentum(events: list[dict], weeks: list[str]) -> dict:
    """
    events: rows with source, metadata, title, week_number, spanning `weeks`.
    weeks: ordered oldest → newest; the last entry is the current week.
    """
    current_week = weeks[-1]
    prior_weeks = weeks[:-1]

    counts: dict[tuple[str, str], dict[str, int]] = {}
    for e in events:
        week = e.get("week_number")
        if week not in weeks:
            continue
        key = track_key(e)
        if not key:
            continue
        track = counts.setdefault((e["source"], key), {w: 0 for w in weeks})
        track[week] += 1

    tracks = []
    for (source, key), by_week in counts.items():
        total = sum(by_week.values())
        if total < MIN_TOTAL_EVENTS:
            continue
        current = by_week[current_week]
        priors = [by_week[w] for w in prior_weeks]
        prior_avg = sum(priors) / len(priors) if priors else 0.0
        tracks.append({
            "source": source,
            "key": key,
            "counts": [by_week[w] for w in weeks],
            "this_week": current,
            "prior_avg": round(prior_avg, 2),
            "trend": classify(current, priors),
        })

    tracks.sort(key=lambda t: (_TREND_ORDER[t["trend"]], -t["this_week"], t["key"]))
    return {"weeks": weeks, "tracks": tracks}


def momentum_summary_for_prompt(momentum: dict) -> str:
    """Compact factual lines for the analysis prompt."""
    tracks = momentum.get("tracks", [])
    if not tracks:
        return "No multi-week history yet — first weeks of data."
    lines = []
    for t in tracks[:30]:
        lines.append(
            f"{t['trend'].upper()}: {t['source']}/{t['key']} — "
            f"{t['this_week']} this week vs {t['prior_avg']}/week prior avg "
            f"(weekly counts {t['counts']})"
        )
    return "\n".join(lines)
