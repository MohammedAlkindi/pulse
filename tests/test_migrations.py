import sqlite3

from agent.store import db
from agent.store.migrations import LATEST_VERSION, apply_migrations, current_version


def tables(path):
    con = sqlite3.connect(path)
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()
        return {r[0] for r in rows}
    finally:
        con.close()


class TestMigrations:
    def test_fresh_database_reaches_latest_version(self, tmp_path):
        path = tmp_path / "fresh.db"
        db.init_db(path)
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        try:
            assert current_version(con) == LATEST_VERSION
        finally:
            con.close()
        expected = {"events", "briefings", "sync_state", "workstreams",
                    "workstream_members", "link_suggestions", "items",
                    "item_history", "events_fts", "schema_version"}
        assert expected <= tables(path)

    def test_migrations_are_idempotent(self, tmp_path):
        path = tmp_path / "twice.db"
        db.init_db(path)
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        try:
            assert apply_migrations(con) == []
        finally:
            con.close()

    def test_pre_versioning_database_upgrades_without_replaying_baseline(self, tmp_path):
        # Simulate a real v1-era database: old schema, one historic row,
        # no schema_version table.
        path = tmp_path / "legacy.db"
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE events (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, event_type TEXT NOT NULL,
                title TEXT, metadata TEXT, occurred_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL, week_number TEXT NOT NULL
            );
            CREATE TABLE briefings (
                id TEXT PRIMARY KEY, week_number TEXT NOT NULL, generated_at TEXT NOT NULL,
                delivered INTEGER DEFAULT 0, content TEXT NOT NULL
            );
            INSERT INTO events VALUES
                ('github:legacy', 'github', 'commit', 'old commit', '{}',
                 '2026-07-01T00:00:00+00:00', '2026-07-01T00:00:01+00:00', '2026-W27');
        """)
        con.commit()
        con.close()

        db.init_db(path)

        events = db.get_events_for_week("2026-W27", path)
        assert len(events) == 1
        assert events[0]["id"] == "github:legacy"
        assert events[0]["actor"] == ""       # new column, defaulted
        assert events[0]["deleted"] == 0

        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        try:
            assert current_version(con) == LATEST_VERSION
        finally:
            con.close()
