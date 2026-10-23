"""Run the whole Pulse pipeline against the synthetic corpus, no credentials.

Everything except the optional LLM analysis step is exercised: ingestion,
workstream resolution, momentum, extraction, the items ledger, and the
evidence-backed briefing. Without an API key the model stage is skipped and
the briefing renders from deterministic evidence alone — which is the point:
the operating review stands up without an LLM in the loop.
"""

import logging
from datetime import datetime
from pathlib import Path

from agent import clock, paths
from agent.config import Config
from agent.store import db

logger = logging.getLogger(__name__)

DEMO_DIR_NAME = "demo"

DEMO_CONFIG = Config({
    "sources": {"gmail": {"enabled": False}, "github": {"enabled": False}, "notion": {"enabled": False}},
    "analysis": {"model": "claude-opus-5"},
    "briefing": {"enabled": False},
    "workstreams": [
        {"name": "OmanX", "aliases": ["omanx", "oman scholars"]},
        {"name": "Grad school applications", "aliases": ["grad school"]},
    ],
})


def use_demo_paths(root: Path | None = None) -> Path:
    """Point every artifact at data/demo/ so the demo can never touch or
    overwrite a real local database or briefing."""
    demo_root = Path(root) if root else paths.DATA_DIR / DEMO_DIR_NAME
    demo_root.mkdir(parents=True, exist_ok=True)
    paths.DB_PATH = demo_root / "pulse.db"
    paths.BRIEFING_DRAFT = demo_root / "briefing_draft.md"
    paths.MANIFEST_PATH = demo_root / "manifest.jsonl"
    return demo_root


def seed(reset: bool = True) -> dict:
    """Load the synthetic corpus into the (demo) ledger. Idempotent."""
    from agent.demo.corpus import build_corpus

    db.init_db()
    if reset:
        db.purge_all()
    events = build_corpus()
    new, updated = db.upsert_events(events)
    return {"submitted": len(events), "new": new, "updated": updated}


def use_demo_clock() -> datetime:
    """Pin "now" to the corpus anchor. The corpus is fixed to 2026-W31, so
    analyzing the current week would find no events and render an empty review."""
    from agent.demo.corpus import ANCHOR

    clock.pin(ANCHOR)
    return ANCHOR


def run(reset: bool = True, week: str | None = None) -> dict:
    """Seed and run the full pipeline. Returns a summary dict."""
    from agent.scheduler import run_analysis_and_briefing
    from agent.store.models import iso_week

    stats = seed(reset=reset)
    target_week = week or iso_week(use_demo_clock())
    content = run_analysis_and_briefing(DEMO_CONFIG, target_week, send=False)

    return {
        **stats,
        "week": target_week,
        "briefing_path": str(paths.BRIEFING_DRAFT),
        "briefing_chars": len(content or ""),
        "workstreams": len(db.list_workstreams()),
        "open_items": len(db.list_items(status="open")),
    }
