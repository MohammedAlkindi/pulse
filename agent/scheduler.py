"""Orchestration: runs each enabled source, stores events, triggers analysis."""

import logging
from datetime import datetime, timezone

from agent import manifest
from agent.config import Config
from agent.store.db import count_events_for_week, get_events_for_week, init_db, insert_event
from agent.store.models import iso_week

logger = logging.getLogger(__name__)


def _current_week() -> str:
    return iso_week(datetime.now(timezone.utc))


def run_ingestion(cfg: Config) -> dict[str, int]:
    """
    Run all enabled sources.  Returns {source: new_event_count}.
    Each source failure is logged and skipped — never re-raised.
    """
    results: dict[str, int] = {}

    if cfg.source_enabled("gmail"):
        results["gmail"] = _ingest_source("gmail", cfg)
    else:
        logger.info("[scheduler] gmail disabled.")

    if cfg.source_enabled("github"):
        results["github"] = _ingest_source("github", cfg)
    else:
        logger.info("[scheduler] github disabled.")

    if cfg.source_enabled("notion"):
        results["notion"] = _ingest_source("notion", cfg)
    else:
        logger.info("[scheduler] notion disabled.")

    return results


def _ingest_source(name: str, cfg: Config) -> int:
    from importlib import import_module
    module = import_module(f"agent.sources.{name}")
    new_count = 0
    try:
        events = module.fetch(cfg)
        for evt in events:
            if insert_event(evt):
                new_count += 1
        manifest.source_result(name, new_count, "ok")
        logger.info("[%s] %d new events stored.", name, new_count)
    except Exception as exc:
        logger.error("[%s] ingestion failed: %s", name, exc)
        manifest.source_result(name, 0, "error", str(exc))
    return new_count


def run_analysis_and_briefing(cfg: Config, week: str, send: bool = False) -> str | None:
    """
    Fetch events for the week, run Claude analysis, generate briefing.
    Returns the briefing content string, or None if generation failed.
    """
    from agent.analysis import analyzer
    from agent.briefing import emailer, generator
    from agent.store.db import Briefing, insert_briefing
    from agent.store.models import Briefing as BriefingModel
    import uuid

    events = get_events_for_week(week)
    counts = count_events_for_week(week)

    analysis = analyzer.analyze(events, cfg)
    content = generator.generate(week, analysis, counts)

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
