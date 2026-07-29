"""Lightweight dataclass schemas matching the SQLite tables."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_week(dt: datetime) -> str:
    """Return 'YYYY-WNN' string for the ISO week containing dt."""
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def content_hash(title: str, metadata: dict, occurred_at: str) -> str:
    """Stable hash of an event's substantive content, for change detection."""
    payload = json.dumps([title or "", metadata or {}, occurred_at], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class Event:
    id: str
    source: str          # 'gmail' | 'github' | 'notion'
    event_type: str      # e.g. 'email_received', 'commit', 'page_updated'
    title: str
    metadata: dict       # source-specific fields; serialised to JSON in db
    occurred_at: str     # ISO 8601, always UTC
    week_number: str     # YYYY-WNN (ISO week of occurred_at)
    ingested_at: str = field(default_factory=_now_iso)
    actor: str = ""               # who did it (sender, commit author, editor)
    canonical_url: str = ""       # stable link to the source record
    source_updated_at: str = ""   # upstream revision timestamp when known
    sensitivity: str = "normal"   # 'normal' | 'sensitive'
    deleted: int = 0              # tombstone: source record no longer exists

    def hash(self) -> str:
        return content_hash(self.title, self.metadata, self.occurred_at)


@dataclass
class Briefing:
    id: str
    week_number: str
    content: str         # full Markdown
    generated_at: str = field(default_factory=_now_iso)
    delivered: int = 0
