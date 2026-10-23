"""The reference time that analysis treats as "now".

Real runs read the wall clock. The demo pins it to its corpus anchor, the same
way it repoints `paths`, so the pipeline, the UI and `ask` all look at the
weeks the synthetic data covers instead of whatever week it is today.
Record timestamps (ingested_at, manifest entries, "Generated" lines) keep the
wall clock: they describe when Pulse ran, not the period under review.
"""

from datetime import date, datetime, timezone

_pinned: datetime | None = None


def now() -> datetime:
    return _pinned or datetime.now(timezone.utc)


def today() -> date:
    return now().date()


def pin(at: datetime | None) -> None:
    """Fix the reference time, or pass None to return to the wall clock."""
    global _pinned
    _pinned = at
