"""Versioned schema migrations.

Each migration is a numbered list of statements applied in one transaction.
Databases created before versioning existed are detected by the presence of
the events table and recorded as already at version 1, so upgrades never
re-run the baseline against real history.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "baseline", [
        """CREATE TABLE IF NOT EXISTS events (
            id          TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            title       TEXT,
            metadata    TEXT,
            occurred_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            week_number TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS briefings (
            id           TEXT PRIMARY KEY,
            week_number  TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            delivered    INTEGER DEFAULT 0,
            content      TEXT NOT NULL
        )""",
    ]),
    (2, "evidence_ledger", [
        "ALTER TABLE events ADD COLUMN actor TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE events ADD COLUMN canonical_url TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE events ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE events ADD COLUMN source_updated_at TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE events ADD COLUMN sensitivity TEXT NOT NULL DEFAULT 'normal'",
        "ALTER TABLE events ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS events_week_idx ON events (week_number)",
        "CREATE INDEX IF NOT EXISTS events_source_idx ON events (source, occurred_at)",
        """CREATE TABLE IF NOT EXISTS sync_state (
            source          TEXT PRIMARY KEY,
            cursor_ts       TEXT NOT NULL DEFAULT '',
            last_success_at TEXT NOT NULL DEFAULT '',
            last_status     TEXT NOT NULL DEFAULT 'never',
            last_error      TEXT NOT NULL DEFAULT ''
        )""",
        """CREATE TABLE IF NOT EXISTS workstreams (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            kind       TEXT NOT NULL,
            status     TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS workstream_members (
            workstream_id TEXT NOT NULL,
            member_type   TEXT NOT NULL,
            member_key    TEXT NOT NULL,
            origin        TEXT NOT NULL DEFAULT 'deterministic',
            PRIMARY KEY (member_type, member_key)
        )""",
        """CREATE TABLE IF NOT EXISTS link_suggestions (
            id            TEXT PRIMARY KEY,
            workstream_id TEXT NOT NULL,
            member_type   TEXT NOT NULL,
            member_key    TEXT NOT NULL,
            evidence      TEXT NOT NULL DEFAULT '[]',
            confidence    REAL NOT NULL DEFAULT 0,
            status        TEXT NOT NULL DEFAULT 'pending',
            created_at    TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS items (
            id           TEXT PRIMARY KEY,
            kind         TEXT NOT NULL,
            text         TEXT NOT NULL,
            workstream_id TEXT NOT NULL DEFAULT '',
            counterparty TEXT NOT NULL DEFAULT '',
            due_date     TEXT NOT NULL DEFAULT '',
            status       TEXT NOT NULL DEFAULT 'open',
            evidence     TEXT NOT NULL DEFAULT '[]',
            confidence   TEXT NOT NULL DEFAULT '{}',
            first_week   TEXT NOT NULL,
            last_week    TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS item_history (
            seq        INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id    TEXT NOT NULL,
            week       TEXT NOT NULL,
            change     TEXT NOT NULL,
            detail     TEXT NOT NULL DEFAULT '',
            evidence   TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        )""",
    ]),
    (3, "full_text_search", [
        """CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
            event_id UNINDEXED, title, snippet
        )""",
    ]),
    (4, "workstream_assignment", [
        "ALTER TABLE events ADD COLUMN workstream_id TEXT NOT NULL DEFAULT ''",
        "CREATE INDEX IF NOT EXISTS events_workstream_idx ON events (workstream_id, occurred_at)",
    ]),
    (5, "item_trust", [
        "ALTER TABLE items ADD COLUMN trust TEXT NOT NULL DEFAULT 'normal'",
    ]),
]

LATEST_VERSION = MIGRATIONS[-1][0]


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (name,)
    ).fetchone()
    return row is not None


def current_version(con: sqlite3.Connection) -> int:
    if not _table_exists(con, "schema_version"):
        return 0
    row = con.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    value = row["v"] if isinstance(row, sqlite3.Row) else row[0]
    return value or 0


def apply_migrations(con: sqlite3.Connection) -> list[int]:
    """Bring the database to LATEST_VERSION. Returns versions applied."""
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
    )

    # Pre-versioning database: history exists but no version rows — record
    # the baseline as applied instead of replaying it.
    if current_version(con) == 0 and _table_exists(con, "events"):
        con.execute(
            "INSERT OR IGNORE INTO schema_version (version, name, applied_at) VALUES (1, 'baseline', datetime('now'))"
        )

    applied = []
    version = current_version(con)
    for number, name, statements in MIGRATIONS:
        if number <= version:
            continue
        for stmt in statements:
            con.execute(stmt)
        con.execute(
            "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, datetime('now'))",
            (number, name),
        )
        applied.append(number)
        logger.info("[migrations] applied %d (%s)", number, name)
    return applied
