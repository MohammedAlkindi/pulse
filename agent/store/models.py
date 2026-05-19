"""Lightweight dataclass schemas matching the SQLite tables."""

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_week(dt: datetime) -> str:
    """Return 'YYYY-WNN' string for the ISO week containing dt."""
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


@dataclass
class Event:
    id: str
    source: str          # 'gmail' | 'github' | 'notion'
    event_type: str      # e.g. 'email_received', 'commit', 'page_updated'
    title: str
    metadata: dict       # source-specific fields; serialised to JSON in db
    occurred_at: str     # ISO 8601
    week_number: str     # YYYY-WNN
    ingested_at: str = field(default_factory=_now_iso)


@dataclass
class Briefing:
    id: str
    week_number: str
    content: str         # full Markdown
    generated_at: str = field(default_factory=_now_iso)
    delivered: int = 0
