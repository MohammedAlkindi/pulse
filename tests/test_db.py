import json

import pytest

from agent.store import db
from agent.store.models import Briefing, Event


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "pulse.db"
    db.init_db(path)
    return path


def make_event(eid="e1", week="2026-W31", source="github", event_type="commit", **meta):
    return Event(
        id=eid, source=source, event_type=event_type, title=f"title-{eid}",
        metadata=meta, occurred_at="2026-07-29T10:00:00+00:00", week_number=week,
    )


class TestEvents:
    def test_insert_returns_true_for_new(self, tmp_db):
        assert db.insert_event(make_event(), tmp_db) is True

    def test_insert_is_idempotent_by_id(self, tmp_db):
        db.insert_event(make_event("dup"), tmp_db)
        assert db.insert_event(make_event("dup"), tmp_db) is False
        assert len(db.get_events_for_week("2026-W31", tmp_db)) == 1

    def test_get_events_parses_metadata_and_orders_by_time(self, tmp_db):
        late = make_event("b", repo="pulse")
        early = Event(
            id="a", source="github", event_type="commit", title="early",
            metadata={"repo": "dx"}, occurred_at="2026-07-28T09:00:00+00:00",
            week_number="2026-W31",
        )
        db.insert_event(late, tmp_db)
        db.insert_event(early, tmp_db)
        events = db.get_events_for_week("2026-W31", tmp_db)
        assert [e["id"] for e in events] == ["a", "b"]
        assert events[1]["metadata"] == {"repo": "pulse"}

    def test_get_events_survives_corrupt_metadata(self, tmp_db):
        db.insert_event(make_event("x"), tmp_db)
        import sqlite3
        con = sqlite3.connect(tmp_db)
        con.execute("UPDATE events SET metadata = 'not-json' WHERE id = 'x'")
        con.commit(); con.close()
        events = db.get_events_for_week("2026-W31", tmp_db)
        assert events[0]["metadata"] == {}

    def test_counts_group_by_source(self, tmp_db):
        db.insert_event(make_event("1", source="github"), tmp_db)
        db.insert_event(make_event("2", source="github"), tmp_db)
        db.insert_event(make_event("3", source="gmail", event_type="email_received"), tmp_db)
        assert db.count_events_for_week("2026-W31", tmp_db) == {"github": 2, "gmail": 1}

    def test_week_filter_excludes_other_weeks(self, tmp_db):
        db.insert_event(make_event("w1", week="2026-W30"), tmp_db)
        db.insert_event(make_event("w2", week="2026-W31"), tmp_db)
        assert len(db.get_events_for_week("2026-W30", tmp_db)) == 1


class TestBriefings:
    def test_insert_and_fetch_latest(self, tmp_db):
        db.insert_briefing(Briefing(id="b1", week_number="2026-W31", content="# one"), tmp_db)
        db.insert_briefing(Briefing(id="b2", week_number="2026-W31", content="# two"), tmp_db)
        row = db.get_briefing_for_week("2026-W31", tmp_db)
        assert row["content"] in ("# one", "# two")
        assert db.get_briefing_for_week("2026-W99", tmp_db) is None

    def test_mark_delivered(self, tmp_db):
        db.insert_briefing(Briefing(id="b1", week_number="2026-W31", content="c"), tmp_db)
        db.mark_delivered("b1", tmp_db)
        assert db.get_briefing_for_week("2026-W31", tmp_db)["delivered"] == 1
