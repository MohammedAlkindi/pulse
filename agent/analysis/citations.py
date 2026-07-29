"""Citation validation and evidence-derived confidence.

The rule that keeps briefings honest: no claim ships without evidence the
system actually holds. Validation is structural and unforgiving — an item
citing anything outside the allowed evidence set is rejected, not repaired.

Confidence is computed from evidence properties (count, source spread,
recency), never taken from a model's self-report.
"""

from datetime import datetime


def validate_citations(entries: list[dict], allowed_ids: set[str]) -> tuple[list[dict], list[dict]]:
    """
    Split entries into (valid, rejected). An entry is valid only when its
    evidence list is non-empty and every id is in allowed_ids.
    """
    valid, rejected = [], []
    for entry in entries:
        evidence = entry.get("evidence")
        if (isinstance(evidence, list) and evidence
                and all(isinstance(e, str) and e in allowed_ids for e in evidence)):
            valid.append(entry)
        else:
            rejected.append(entry)
    return valid, rejected


def _week_distance(week_a: str, week_b: str) -> int:
    """Approximate distance in weeks between two YYYY-WNN keys."""
    try:
        ya, wa = week_a.split("-W")
        yb, wb = week_b.split("-W")
        return abs((int(ya) * 53 + int(wa)) - (int(yb) * 53 + int(wb)))
    except (ValueError, AttributeError):
        return 99


def derive_confidence(evidence_events: list[dict], current_week: str) -> dict:
    """
    Deterministic confidence from evidence quality:
      high   — two or more events, or corroboration across two sources
      medium — a single event from the current or previous week
      low    — anything thinner
    """
    count = len(evidence_events)
    sources = {e.get("source") for e in evidence_events if e.get("source")}
    weeks = [e.get("week_number", "") for e in evidence_events]
    recency = min((_week_distance(w, current_week) for w in weeks), default=99)

    if count >= 2 or len(sources) >= 2:
        level = "high"
    elif count == 1 and recency <= 1:
        level = "medium"
    else:
        level = "low"

    return {
        "level": level,
        "basis": {
            "evidence_count": count,
            "distinct_sources": sorted(sources),
            "most_recent_weeks_ago": recency,
        },
    }
