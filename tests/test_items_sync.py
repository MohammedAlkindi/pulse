import pytest

from agent.analysis.items_sync import similarity, stale_open_items, sync_items, resolve_item
from agent.store import db


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "pulse.db"
    db.init_db(path)
    return path


def cand(text, kind="commitment_by_user", evidence=None, due="", week="2026-W31"):
    return {"kind": kind, "text": text, "evidence": evidence or ["gmail:1"],
            "counterparty": "Sarah", "due_date": due, "week": week}


class TestSimilarity:
    def test_paraphrase_scores_high(self):
        a = "I'll send Sarah the Q3 numbers by Friday"
        b = "send Sarah the Q3 numbers"
        assert similarity(a, b) >= 0.5

    def test_unrelated_scores_low(self):
        assert similarity("ship the dashboard", "renew my passport") < 0.2


class TestSyncItems:
    def test_new_candidates_create_items_with_history(self, tmp_db):
        result = sync_items([cand("I'll send the Q3 numbers by Friday")], "2026-W31", db_path=tmp_db)
        assert result == {"created": 1, "reseen": 0}
        items = db.list_items(db_path=tmp_db)
        assert items[0]["status"] == "open"
        history = db.get_item_history(items[0]["id"], tmp_db)
        assert [h["change"] for h in history] == ["created"]

    def test_reseen_item_merges_instead_of_duplicating(self, tmp_db):
        sync_items([cand("I'll send the Q3 numbers by Friday", evidence=["gmail:1"])],
                   "2026-W31", db_path=tmp_db)
        result = sync_items([cand("I'll send the Q3 numbers", evidence=["gmail:2"])],
                            "2026-W32", db_path=tmp_db)
        assert result == {"created": 0, "reseen": 1}

        items = db.list_items(db_path=tmp_db)
        assert len(items) == 1
        assert items[0]["evidence"] == ["gmail:1", "gmail:2"]  # union, sorted
        assert items[0]["first_week"] == "2026-W31"
        assert items[0]["last_week"] == "2026-W32"

        changes = [h["change"] for h in db.get_item_history(items[0]["id"], tmp_db)]
        assert changes == ["created", "seen"]

    def test_different_kinds_never_merge(self, tmp_db):
        sync_items([cand("send the Q3 numbers", kind="commitment_by_user")], "2026-W31", db_path=tmp_db)
        sync_items([cand("send the Q3 numbers", kind="question")], "2026-W31", db_path=tmp_db)
        assert len(db.list_items(db_path=tmp_db)) == 2

    def test_confidence_is_derived_from_evidence(self, tmp_db):
        index = {
            "gmail:1": {"source": "gmail", "week_number": "2026-W31"},
            "github:9": {"source": "github", "week_number": "2026-W31"},
        }
        sync_items([cand("ship it", evidence=["gmail:1", "github:9"])],
                   "2026-W31", event_index=index, db_path=tmp_db)
        item = db.list_items(db_path=tmp_db)[0]
        assert item["confidence"]["level"] == "high"
        assert item["confidence"]["basis"]["evidence_count"] == 2


class TestLifecycle:
    def test_resolution_appends_history_and_keeps_the_row(self, tmp_db):
        sync_items([cand("send the deck")], "2026-W31", db_path=tmp_db)
        item = db.list_items(db_path=tmp_db)[0]
        resolve_item(item["id"], "2026-W32", note="sent Tuesday", db_path=tmp_db)

        refreshed = db.list_items(db_path=tmp_db)[0]
        assert refreshed["status"] == "resolved"
        changes = [h["change"] for h in db.get_item_history(item["id"], tmp_db)]
        assert changes == ["created", "status:resolved"]

    def test_resolved_items_do_not_absorb_new_candidates(self, tmp_db):
        sync_items([cand("send the deck")], "2026-W31", db_path=tmp_db)
        item = db.list_items(db_path=tmp_db)[0]
        resolve_item(item["id"], "2026-W31", db_path=tmp_db)

        sync_items([cand("send the deck")], "2026-W33", db_path=tmp_db)
        items = db.list_items(db_path=tmp_db)
        assert len(items) == 2  # the promise came back as a fresh open item

    def test_stale_detection(self, tmp_db):
        sync_items([cand("old promise")], "2026-W29", db_path=tmp_db)
        sync_items([cand("fresh promise about visas")], "2026-W31", db_path=tmp_db)
        stale = stale_open_items("2026-W31", min_weeks_open=1, db_path=tmp_db)
        assert [s["text"] for s in stale] == ["old promise"]
