import pytest

from agent.store import db
from agent.store.models import Event


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "pulse.db"
    db.init_db(path)
    return path


def ev(eid="e1", title="fix parser", snippet="", url="", actor="mo", week="2026-W31"):
    meta = {"repo": "Pulse"}
    if snippet:
        meta["snippet"] = snippet
    return Event(
        id=eid, source="github", event_type="commit", title=title, metadata=meta,
        occurred_at="2026-07-29T10:00:00+00:00", week_number=week,
        actor=actor, canonical_url=url,
    )


class TestUpsert:
    def test_reingesting_identical_events_creates_zero_duplicates(self, tmp_db):
        batch = [ev("a"), ev("b")]
        assert db.upsert_events(batch, tmp_db) == (2, 0)
        assert db.upsert_events(batch, tmp_db) == (0, 0)
        assert len(db.get_events_for_week("2026-W31", tmp_db)) == 2

    def test_changed_content_updates_in_place(self, tmp_db):
        db.upsert_events([ev("a", title="WIP")], tmp_db)
        before = db.get_events_by_ids(["a"], tmp_db)[0]

        assert db.upsert_events([ev("a", title="WIP — merged")], tmp_db) == (0, 1)
        after = db.get_events_by_ids(["a"], tmp_db)[0]

        assert after["title"] == "WIP — merged"
        assert after["ingested_at"] == before["ingested_at"]
        assert after["source_updated_at"] != ""
        assert after["content_hash"] != before["content_hash"]

    def test_ledger_columns_round_trip(self, tmp_db):
        db.upsert_events([ev("a", url="https://github.com/x/y/commit/abc")], tmp_db)
        row = db.get_events_by_ids(["a"], tmp_db)[0]
        assert row["actor"] == "mo"
        assert row["canonical_url"] == "https://github.com/x/y/commit/abc"
        assert row["sensitivity"] == "normal"

    def test_deleted_events_are_excluded_from_week_queries(self, tmp_db):
        tomb = ev("gone")
        tomb.deleted = 1
        db.upsert_events([tomb, ev("here")], tmp_db)
        ids = [e["id"] for e in db.get_events_for_week("2026-W31", tmp_db)]
        assert ids == ["here"]


class TestSearch:
    def test_finds_by_title_and_snippet(self, tmp_db):
        db.upsert_events([
            ev("a", title="deploy DashboardX to vercel"),
            ev("b", title="unrelated", snippet="momentum engine notes"),
        ], tmp_db)
        assert [e["id"] for e in db.search_events("vercel", db_path=tmp_db)] == ["a"]
        assert [e["id"] for e in db.search_events("momentum", db_path=tmp_db)] == ["b"]

    def test_hostile_query_syntax_is_neutralised(self, tmp_db):
        db.upsert_events([ev("a", title="normal event")], tmp_db)
        for hostile in ['title:x OR 1', 'NEAR(a b)', '"unclosed', "x* AND y", "-"]:
            db.search_events(hostile, db_path=tmp_db)  # must not raise

    def test_empty_query_returns_nothing(self, tmp_db):
        assert db.search_events("   ", db_path=tmp_db) == []


class TestSyncState:
    def test_ok_status_stamps_success_and_cursor(self, tmp_db):
        db.set_sync_state("github", cursor_ts="2026-07-29T00:00:00+00:00", status="ok", db_path=tmp_db)
        state = db.get_sync_state("github", tmp_db)
        assert state["last_status"] == "ok"
        assert state["cursor_ts"] == "2026-07-29T00:00:00+00:00"
        assert state["last_success_at"] != ""

    def test_error_keeps_previous_cursor_and_success(self, tmp_db):
        db.set_sync_state("github", cursor_ts="2026-07-29T00:00:00+00:00", status="ok", db_path=tmp_db)
        success = db.get_sync_state("github", tmp_db)["last_success_at"]
        db.set_sync_state("github", status="error", error="boom", db_path=tmp_db)
        state = db.get_sync_state("github", tmp_db)
        assert state["cursor_ts"] == "2026-07-29T00:00:00+00:00"
        assert state["last_success_at"] == success
        assert state["last_error"] == "boom"

    def test_unknown_source_is_none(self, tmp_db):
        assert db.get_sync_state("carrier-pigeon", tmp_db) is None


class TestWorkstreamsStore:
    def test_member_map_round_trips(self, tmp_db):
        db.upsert_workstream("ws1", "Pulse", "repo", tmp_db)
        db.add_workstream_member("ws1", "github_repo", "MohammedAlkindi/Pulse", db_path=tmp_db)
        db.add_workstream_member("ws1", "alias", "pulse", db_path=tmp_db)
        assert db.get_member_map(tmp_db) == {
            ("github_repo", "MohammedAlkindi/Pulse"): "ws1",
            ("alias", "pulse"): "ws1",
        }

    def test_member_keys_are_unique(self, tmp_db):
        db.upsert_workstream("ws1", "A", "repo", tmp_db)
        db.upsert_workstream("ws2", "B", "repo", tmp_db)
        db.add_workstream_member("ws1", "alias", "shared", db_path=tmp_db)
        db.add_workstream_member("ws2", "alias", "shared", db_path=tmp_db)  # ignored
        assert db.get_member_map(tmp_db)[("alias", "shared")] == "ws1"

    def test_link_suggestions_queue(self, tmp_db):
        db.upsert_workstream("ws1", "Pulse", "repo", tmp_db)
        db.add_link_suggestion("ws1", "gmail_thread", "t1", ["gmail:1"], 0.6, tmp_db)
        pending = db.list_link_suggestions(db_path=tmp_db)
        assert len(pending) == 1
        assert pending[0]["evidence"] == ["gmail:1"]
        assert pending[0]["status"] == "pending"


class TestItemsStore:
    ITEM = {
        "id": "it1", "kind": "commitment_by_user",
        "text": "Send Sarah the Q3 numbers", "counterparty": "Sarah",
        "due_date": "2026-08-01", "evidence": ["gmail:1"],
        "confidence": {"basis": "single_source"},
        "first_week": "2026-W31", "last_week": "2026-W31",
    }

    def test_insert_and_list(self, tmp_db):
        db.insert_item(self.ITEM, tmp_db)
        items = db.list_items(db_path=tmp_db)
        assert items[0]["evidence"] == ["gmail:1"]
        assert items[0]["status"] == "open"

    def test_update_preserves_other_fields(self, tmp_db):
        db.insert_item(self.ITEM, tmp_db)
        db.update_item("it1", status="resolved", last_week="2026-W32", db_path=tmp_db)
        item = db.list_items(db_path=tmp_db)[0]
        assert item["status"] == "resolved"
        assert item["last_week"] == "2026-W32"
        assert item["text"] == "Send Sarah the Q3 numbers"

    def test_history_is_append_only(self, tmp_db):
        db.insert_item(self.ITEM, tmp_db)
        db.append_item_history("it1", "2026-W31", "created", evidence=["gmail:1"], db_path=tmp_db)
        db.append_item_history("it1", "2026-W32", "status:resolved", db_path=tmp_db)
        history = db.get_item_history("it1", tmp_db)
        assert [h["change"] for h in history] == ["created", "status:resolved"]

    def test_dated_items_sort_before_undated(self, tmp_db):
        db.insert_item({**self.ITEM, "id": "undated", "due_date": ""}, tmp_db)
        db.insert_item({**self.ITEM, "id": "dated"}, tmp_db)
        assert [i["id"] for i in db.list_items(db_path=tmp_db)] == ["dated", "undated"]


class TestRetention:
    def test_export_then_purge_leaves_empty_tables(self, tmp_db):
        db.upsert_events([ev("a")], tmp_db)
        db.insert_item(TestItemsStore.ITEM, tmp_db)
        export = db.export_all(tmp_db)
        assert len(export["events"]) == 1
        assert len(export["items"]) == 1

        db.purge_all(tmp_db)
        assert db.export_all(tmp_db)["events"] == []
        assert db.search_events("fix", db_path=tmp_db) == []
