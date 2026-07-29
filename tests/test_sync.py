from datetime import datetime, timedelta, timezone
from functools import partial

import pytest

from agent import scheduler
from agent.config import Config
from agent.store import db
from agent.store.models import Event, iso_week

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
CFG = Config({"sources": {"github": {"enabled": True, "lookback_days": 7}}})


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "pulse.db"
    db.init_db(path)
    # Rebind the store functions the scheduler imported so everything in this
    # module operates on the temp database.
    monkeypatch.setattr(scheduler, "get_sync_state", partial(db.get_sync_state, db_path=path))
    monkeypatch.setattr(scheduler, "set_sync_state", partial(db.set_sync_state, db_path=path))
    monkeypatch.setattr(scheduler, "upsert_events", partial(db.upsert_events, db_path=path))
    return path


def make_event(eid, week=None, occurred=None):
    occurred = occurred or NOW
    return Event(
        id=eid, source="github", event_type="commit", title=f"t-{eid}",
        metadata={"repo": "Pulse"}, occurred_at=occurred.isoformat(),
        week_number=week or iso_week(occurred),
    )


class TestSyncWindow:
    def test_no_cursor_uses_lookback(self, tmp_db):
        start = scheduler.sync_window_start("github", CFG, NOW)
        assert start == NOW - timedelta(days=7)

    def test_recent_cursor_never_shrinks_below_lookback(self, tmp_db):
        db.set_sync_state("github", cursor_ts=(NOW - timedelta(days=1)).isoformat(),
                          status="ok", db_path=tmp_db)
        start = scheduler.sync_window_start("github", CFG, NOW)
        assert start == NOW - timedelta(days=7)

    def test_old_cursor_extends_window_with_overlap(self, tmp_db):
        # Agent was off for 20 days: the window must reach back past the gap.
        db.set_sync_state("github", cursor_ts=(NOW - timedelta(days=20)).isoformat(),
                          status="ok", db_path=tmp_db)
        start = scheduler.sync_window_start("github", CFG, NOW)
        assert start == NOW - timedelta(days=22)  # cursor minus 2-day overlap

    def test_ancient_cursor_is_capped(self, tmp_db):
        db.set_sync_state("github", cursor_ts=(NOW - timedelta(days=90)).isoformat(),
                          status="ok", db_path=tmp_db)
        start = scheduler.sync_window_start("github", CFG, NOW)
        assert start == NOW - scheduler.MAX_SYNC_WINDOW

    def test_malformed_cursor_falls_back_to_lookback(self, tmp_db):
        db.set_sync_state("github", cursor_ts="not-a-date", status="ok", db_path=tmp_db)
        assert scheduler.sync_window_start("github", CFG, NOW) == NOW - timedelta(days=7)


class TestIngestSource:
    def test_success_stores_events_and_advances_cursor(self, tmp_db):
        result = scheduler._ingest_source(
            "github", CFG, fetcher=lambda cfg, since: [make_event("a"), make_event("b")], now=NOW,
        )
        assert result == {"new": 2, "updated": 0, "status": "ok"}
        state = db.get_sync_state("github", tmp_db)
        assert state["last_status"] == "ok"
        assert state["cursor_ts"] == NOW.isoformat()
        assert len(db.get_events_for_week(iso_week(NOW), tmp_db)) == 2

    def test_rerun_is_idempotent(self, tmp_db):
        fetcher = lambda cfg, since: [make_event("a")]
        scheduler._ingest_source("github", CFG, fetcher=fetcher, now=NOW)
        result = scheduler._ingest_source("github", CFG, fetcher=fetcher, now=NOW)
        assert result["new"] == 0
        assert len(db.get_events_for_week(iso_week(NOW), tmp_db)) == 1

    def test_failure_records_error_and_preserves_cursor(self, tmp_db):
        scheduler._ingest_source("github", CFG, fetcher=lambda cfg, since: [make_event("a")], now=NOW)

        def broken(cfg, since):
            raise RuntimeError("token expired")

        later = NOW + timedelta(days=7)
        result = scheduler._ingest_source("github", CFG, fetcher=broken, now=later)
        assert result["status"] == "error"
        assert "token expired" in result["error"]

        state = db.get_sync_state("github", tmp_db)
        assert state["last_status"] == "error"
        assert state["cursor_ts"] == NOW.isoformat()  # unchanged — resume covers the gap
        # And the next window reaches back across the failed period.
        start = scheduler.sync_window_start("github", CFG, later)
        assert start <= NOW - timedelta(days=1)

    def test_one_source_failure_leaves_other_sources_data_intact(self, tmp_db):
        scheduler._ingest_source("github", CFG, fetcher=lambda cfg, since: [make_event("g1")], now=NOW)

        def broken(cfg, since):
            raise RuntimeError("gmail down")

        scheduler._ingest_source("gmail", CFG, fetcher=broken, now=NOW)
        ids = [e["id"] for e in db.get_events_for_week(iso_week(NOW), tmp_db)]
        assert ids == ["g1"]
        assert db.get_sync_state("gmail", tmp_db)["last_status"] == "error"
        assert db.get_sync_state("github", tmp_db)["last_status"] == "ok"

    def test_fetcher_receives_the_window_start(self, tmp_db):
        seen = {}

        def spy(cfg, since):
            seen["since"] = since
            return []

        scheduler._ingest_source("github", CFG, fetcher=spy, now=NOW)
        assert seen["since"] == NOW - timedelta(days=7)
