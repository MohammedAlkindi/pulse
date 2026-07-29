"""SQLite connection, migrations, and CRUD operations."""

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Generator

from agent.paths import DB_PATH
from agent.store.models import Briefing, Event

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    title       TEXT,
    metadata    TEXT,
    occurred_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    week_number TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS briefings (
    id           TEXT PRIMARY KEY,
    week_number  TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    delivered    INTEGER DEFAULT 0,
    content      TEXT NOT NULL
);
"""


@contextmanager
def _conn(db_path: Path = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn(db_path) as con:
        con.executescript(_SCHEMA)
    logger.debug("Database initialised at %s", db_path)


# ── events ──────────────────────────────────────────────────────────────────

def insert_event(event: Event, db_path: Path = DB_PATH) -> bool:
    """Insert event; return True if new, False if duplicate (idempotent)."""
    sql = """
        INSERT OR IGNORE INTO events
            (id, source, event_type, title, metadata, occurred_at, ingested_at, week_number)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    with _conn(db_path) as con:
        cur = con.execute(sql, (
            event.id,
            event.source,
            event.event_type,
            event.title,
            json.dumps(event.metadata),
            event.occurred_at,
            event.ingested_at,
            event.week_number,
        ))
        return cur.rowcount > 0


def get_events_for_week(week: str, db_path: Path = DB_PATH) -> list[dict]:
    sql = "SELECT * FROM events WHERE week_number = ? ORDER BY occurred_at"
    with _conn(db_path) as con:
        rows = con.execute(sql, (week,)).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["metadata"] = json.loads(d["metadata"] or "{}")
        except json.JSONDecodeError:
            d["metadata"] = {}
        result.append(d)
    return result


def count_events_for_week(week: str, db_path: Path = DB_PATH) -> dict[str, int]:
    sql = "SELECT source, COUNT(*) as n FROM events WHERE week_number = ? GROUP BY source"
    with _conn(db_path) as con:
        rows = con.execute(sql, (week,)).fetchall()
    return {row["source"]: row["n"] for row in rows}


def count_events_by_type_for_week(week: str, db_path: Path = DB_PATH) -> dict[str, dict[str, int]]:
    """Return {source: {event_type: count}} for one week."""
    sql = """
        SELECT source, event_type, COUNT(*) as n
        FROM events WHERE week_number = ?
        GROUP BY source, event_type
    """
    with _conn(db_path) as con:
        rows = con.execute(sql, (week,)).fetchall()
    result: dict[str, dict[str, int]] = {}
    for row in rows:
        result.setdefault(row["source"], {})[row["event_type"]] = row["n"]
    return result


# ── briefings ────────────────────────────────────────────────────────────────

def insert_briefing(briefing: Briefing, db_path: Path = DB_PATH) -> None:
    sql = """
        INSERT OR REPLACE INTO briefings (id, week_number, generated_at, delivered, content)
        VALUES (?, ?, ?, ?, ?)
    """
    with _conn(db_path) as con:
        con.execute(sql, (
            briefing.id,
            briefing.week_number,
            briefing.generated_at,
            briefing.delivered,
            briefing.content,
        ))


def mark_delivered(briefing_id: str, db_path: Path = DB_PATH) -> None:
    with _conn(db_path) as con:
        con.execute(
            "UPDATE briefings SET delivered = 1 WHERE id = ?",
            (briefing_id,),
        )


def get_briefing_for_week(week: str, db_path: Path = DB_PATH) -> dict | None:
    with _conn(db_path) as con:
        row = con.execute(
            "SELECT * FROM briefings WHERE week_number = ? ORDER BY generated_at DESC LIMIT 1",
            (week,),
        ).fetchone()
    return dict(row) if row else None
