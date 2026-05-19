"""Append-only JSONL run audit trail."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from agent.paths import MANIFEST_PATH

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(event: str, payload: dict | None = None) -> None:
    """Append one line to the manifest JSONL file."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": _now(), "event": event, **(payload or {})}
    try:
        with MANIFEST_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        logger.warning("manifest write failed: %s", exc)


def run_start(config_path: str, flags: dict) -> None:
    record("run_start", {"config": config_path, "flags": flags})


def run_end(summary: dict) -> None:
    record("run_end", summary)


def source_result(source: str, count: int, status: str, error: str | None = None) -> None:
    record("source_result", {"source": source, "count": count, "status": status, "error": error})


def briefing_generated(week: str, path: str) -> None:
    record("briefing_generated", {"week": week, "path": path})


def briefing_delivered(week: str, recipient: str) -> None:
    record("briefing_delivered", {"week": week, "recipient": recipient})
