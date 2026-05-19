"""Canonical path resolution for all Pulse artifacts."""

from pathlib import Path

# Project root is one level above this file (agent/)
ROOT = Path(__file__).parent.parent.resolve()

DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"
CONFIG_DIR = ROOT / "config"
TEMPLATES_DIR = ROOT / "templates"

DB_PATH = DATA_DIR / "pulse.db"
BRIEFING_DRAFT = LOGS_DIR / "briefing_draft.md"
MANIFEST_PATH = LOGS_DIR / "manifest.jsonl"


def ensure_dirs() -> None:
    for d in (DATA_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
