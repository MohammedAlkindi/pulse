"""Orchestration: runs each enabled source, stores events, triggers analysis."""

import logging
from datetime import datetime, timedelta, timezone

from agent import manifest
from agent.config import Config
from agent.store.db import get_events_for_week, get_sync_state, set_sync_state, upsert_events
from agent.store.models import iso_week

logger = logging.getLogger(__name__)

SOURCES = ("gmail", "github", "notion")

# Overlap re-fetches a slice already ingested so late edits and clock skew
# are caught; the idempotent upsert makes this free of duplicates.
SYNC_OVERLAP = timedelta(days=2)
# Upper bound on catch-up after long gaps (GitHub's events API only reaches
# back ~90 days / 300 events anyway).
MAX_SYNC_WINDOW = timedelta(days=30)


def _current_week() -> str:
    return iso_week(datetime.now(timezone.utc))


def sync_window_start(source: str, cfg: Config, now: datetime) -> datetime:
    """Where this sync should start: the stored cursor minus overlap (bounded),
    but never less than the configured lookback."""
    lookback = timedelta(days=cfg.source_cfg(source).get("lookback_days", 7))
    default_start = now - lookback
    state = get_sync_state(source)
    if not state or not state.get("cursor_ts"):
        return default_start
    try:
        cursor = datetime.fromisoformat(state["cursor_ts"])
    except ValueError:
        return default_start
    start = cursor - SYNC_OVERLAP
    start = max(start, now - MAX_SYNC_WINDOW)
    return min(start, default_start)


def run_ingestion(cfg: Config) -> dict[str, dict]:
    """
    Run all enabled sources. Returns {source: {new, updated, status[, error]}}.
    Each source failure is isolated: recorded in sync_state and the result,
    never allowed to affect other sources' data.
    """
    results: dict[str, dict] = {}
    for name in SOURCES:
        if cfg.source_enabled(name):
            results[name] = _ingest_source(name, cfg)
        else:
            results[name] = {"new": 0, "updated": 0, "status": "disabled"}
            logger.info("[scheduler] %s disabled.", name)
    return results


def _ingest_source(name: str, cfg: Config, fetcher=None, now: datetime | None = None) -> dict:
    if fetcher is None:
        from importlib import import_module
        fetcher = import_module(f"agent.sources.{name}").fetch

    now = now or datetime.now(timezone.utc)
    since = sync_window_start(name, cfg, now)

    try:
        events = fetcher(cfg, since=since)
        new, updated = upsert_events(events)
        # The window ran through `now`; that becomes the next cursor. If the
        # source truncated deep history (API caps), overlap won't recover it —
        # that bound is documented, not hidden.
        set_sync_state(name, cursor_ts=now.isoformat(), status="ok")
        manifest.source_result(name, new, "ok")
        logger.info("[%s] %d new, %d updated (window since %s).", name, new, updated, since.date())
        return {"new": new, "updated": updated, "status": "ok"}
    except Exception as exc:
        set_sync_state(name, status="error", error=str(exc)[:500])
        manifest.source_result(name, 0, "error", str(exc))
        logger.error("[%s] ingestion failed: %s", name, exc)
        return {"new": 0, "updated": 0, "status": "error", "error": str(exc)}


def run_analysis_and_briefing(cfg: Config, week: str, send: bool = False,
                              source_status: dict[str, dict] | None = None) -> str | None:
    """
    Fetch events for the week, run analysis, extract items, generate briefing.
    Returns the briefing content string, or None if generation failed.
    """
    from agent.analysis import analyzer
    from agent.analysis.momentum import compute_momentum, momentum_summary_for_prompt, trailing_weeks
    from agent.briefing import emailer, generator
    from agent.store.db import count_events_by_type_for_week, get_events_for_weeks, insert_briefing
    from agent.store.models import Briefing as BriefingModel
    import uuid

    events = get_events_for_week(week)
    counts = count_events_by_type_for_week(week)

    weeks = trailing_weeks(datetime.now(timezone.utc))
    momentum = compute_momentum(get_events_for_weeks(weeks), weeks)

    analysis = analyzer.analyze(events, cfg, momentum_summary_for_prompt(momentum))
    content = generator.generate(week, analysis, counts, momentum,
                                 source_status=source_status)

    briefing_id = str(uuid.uuid4())
    b = BriefingModel(id=briefing_id, week_number=week, content=content)
    insert_briefing(b)

    draft_path = emailer.save_draft(content)
    manifest.briefing_generated(week, str(draft_path))

    if send:
        delivered = emailer.deliver(content, week, cfg, send=True)
        if delivered:
            from agent.store.db import mark_delivered
            mark_delivered(briefing_id)
            manifest.briefing_delivered(week, cfg.briefing.get("recipient_email", ""))

    return content
