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
        # Connector errors routinely quote request headers or URLs; every path
        # that stores or prints one goes through redaction first.
        from agent.secrets import redact
        message = redact(str(exc))[:500]
        set_sync_state(name, status="error", error=message)
        manifest.source_result(name, 0, "error", message)
        logger.error("[%s] ingestion failed: %s", name, message)
        return {"new": 0, "updated": 0, "status": "error", "error": message}


def run_analysis_and_briefing(cfg: Config, week: str, send: bool = False,
                              source_status: dict[str, dict] | None = None) -> str | None:
    """
    The full graph pipeline for one week: workstream resolution, momentum,
    item extraction and persistence, cited analysis, and the evidence-backed
    briefing. Returns the briefing content string.
    """
    from datetime import date
    from agent.analysis import analyzer
    from agent.analysis.extract import extract_candidates
    from agent.analysis.items_sync import stale_open_items, sync_items
    from agent.analysis.momentum import compute_momentum, trailing_weeks
    from agent.briefing import emailer, generator
    from agent.briefing.changes import approaching_deadlines, material_changes
    from agent.graph.workstreams import resolve_events
    from agent.store.db import (count_events_by_type_for_week, get_events_by_ids,
                                get_events_for_weeks, get_events_for_weeks_full,
                                get_unassigned_events, insert_briefing, list_items)
    from agent.store.models import Briefing as BriefingModel
    import uuid

    weeks = trailing_weeks(datetime.now(timezone.utc))

    # 1 · connect events into workstreams (deterministic; ambiguity queues)
    resolve_events(get_unassigned_events(weeks), cfg=cfg)

    events = get_events_for_week(week)
    counts = count_events_by_type_for_week(week)
    event_index = {e["id"]: e for e in events}

    # 2 · computed momentum over the trailing window
    momentum = compute_momentum(get_events_for_weeks(weeks), weeks)

    # 3 · deterministic extraction → persistent items ledger.
    # Runs over the whole trailing window, not just this week: on a first run
    # (or after a gap) the backlog of commitments and blockers still surfaces,
    # and sync_items merges anything already known.
    window_events = get_events_for_weeks_full(weeks)
    window_index = {e["id"]: e for e in window_events}
    known_domains = set(cfg.get("known_domains", default=[]) or [])
    candidates = extract_candidates(window_events, known_domains=known_domains)
    for candidate in candidates:
        anchor = window_index.get(candidate["evidence"][0], {})
        candidate["workstream_id"] = anchor.get("workstream_id", "")
    item_stats = sync_items(candidates, week, event_index=window_index)
    logger.info("[items] %d created, %d re-seen.", item_stats["created"], item_stats["reseen"])

    # 4 · cited model analysis (validated against the evidence context)
    analysis = analyzer.analyze(events, cfg, momentum)

    # 5 · assemble ledger views for the briefing
    open_items = list_items(status="open")
    deadlines = approaching_deadlines(open_items, date.today())
    stale = stale_open_items(week, min_weeks_open=2)
    changes = material_changes(week)

    # The evidence index must cover everything the briefing may cite,
    # including items whose evidence predates this week.
    cited_ids: set[str] = set(event_index)
    for collection in (open_items, stale, *changes.values()):
        for item in collection:
            cited_ids.update(item.get("evidence", []))
    missing = [i for i in cited_ids if i not in event_index]
    for row in get_events_by_ids(missing):
        event_index[row["id"]] = row

    content = generator.generate(
        week, analysis, counts, momentum,
        changes=changes, open_items=open_items, deadlines=deadlines,
        stale_items=stale, event_index=event_index, source_status=source_status,
    )

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
