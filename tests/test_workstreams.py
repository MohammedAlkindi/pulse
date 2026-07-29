import pytest

from agent.config import Config
from agent.graph.workstreams import resolve_events, seed_from_config
from agent.store import db


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "pulse.db"
    db.init_db(path)
    return path


def gh(eid, repo="MohammedAlkindi/Pulse", title="fix sync"):
    return {"id": eid, "source": "github", "event_type": "commit", "title": title,
            "metadata": {"repo": repo}, "week_number": "2026-W31"}


def notion(eid, page_id="p1", database_id="", title="Roadmap"):
    return {"id": eid, "source": "notion", "event_type": "page_updated", "title": title,
            "metadata": {"page_id": page_id, "database_id": database_id}, "week_number": "2026-W31"}


def mail(eid, subject, snippet="", sender="a@example.com", thread="t1"):
    return {"id": eid, "source": "gmail", "event_type": "email_received", "title": subject,
            "metadata": {"snippet": snippet, "sender": sender, "thread_id": thread},
            "week_number": "2026-W31"}


def store(events, path):
    """Persist raw dicts as ledger rows so assignments can be written."""
    from agent.store.models import Event
    db.upsert_events([
        Event(id=e["id"], source=e["source"], event_type=e["event_type"], title=e["title"],
              metadata=e["metadata"], occurred_at="2026-07-29T10:00:00+00:00",
              week_number=e["week_number"])
        for e in events
    ], path)


class TestAnchors:
    def test_repo_events_create_and_join_a_repo_workstream(self, tmp_db):
        events = [gh("a"), gh("b")]
        store(events, tmp_db)
        assignments = resolve_events(events, db_path=tmp_db)
        assert assignments == {"a": "repo:MohammedAlkindi/Pulse", "b": "repo:MohammedAlkindi/Pulse"}
        ws = db.list_workstreams(tmp_db)
        assert len(ws) == 1 and ws[0]["kind"] == "repository" and ws[0]["name"] == "Pulse"

    def test_notion_database_pages_group_under_the_database(self, tmp_db):
        events = [notion("n1", page_id="p1", database_id="db9"),
                  notion("n2", page_id="p2", database_id="db9")]
        store(events, tmp_db)
        assignments = resolve_events(events, db_path=tmp_db)
        assert set(assignments.values()) == {"notion-db:db9"}

    def test_standalone_notion_page_becomes_its_own_workstream(self, tmp_db):
        events = [notion("n1", page_id="p1", title="Thesis Notes")]
        store(events, tmp_db)
        assignments = resolve_events(events, db_path=tmp_db)
        assert assignments["n1"] == "notion-page:p1"
        assert db.list_workstreams(tmp_db)[0]["name"] == "Thesis Notes"

    def test_assignment_is_persisted_on_the_event_rows(self, tmp_db):
        events = [gh("a")]
        store(events, tmp_db)
        resolve_events(events, db_path=tmp_db)
        rows = db.get_events_for_workstream("repo:MohammedAlkindi/Pulse", db_path=tmp_db)
        assert [r["id"] for r in rows] == ["a"]


class TestEmailResolution:
    def test_single_alias_match_links_the_thread_durably(self, tmp_db):
        repo_events = [gh("a")]
        store(repo_events, tmp_db)
        resolve_events(repo_events, db_path=tmp_db)

        first = [mail("m1", "Pulse sync question", thread="t9")]
        store(first, tmp_db)
        assert resolve_events(first, db_path=tmp_db)["m1"] == "repo:MohammedAlkindi/Pulse"

        # A later message in the same thread joins without any alias in text.
        later = [mail("m2", "Re: (no keywords here)", thread="t9")]
        store(later, tmp_db)
        assert resolve_events(later, db_path=tmp_db)["m2"] == "repo:MohammedAlkindi/Pulse"

    def test_ambiguous_match_goes_to_review_queue_not_ground_truth(self, tmp_db):
        seed = [gh("a", repo="u/alpha", title="x"), gh("b", repo="u/beta", title="y")]
        store(seed, tmp_db)
        resolve_events(seed, db_path=tmp_db)

        ambiguous = [mail("m1", "alpha and beta status", thread="t2")]
        store(ambiguous, tmp_db)
        assignments = resolve_events(ambiguous, db_path=tmp_db)

        assert "m1" not in assignments  # never silently guessed
        pending = db.list_link_suggestions(db_path=tmp_db)
        assert {p["workstream_id"] for p in pending} == {"repo:u/alpha", "repo:u/beta"}
        assert all(p["evidence"] == ["m1"] for p in pending)

    def test_no_match_stays_unassigned(self, tmp_db):
        events = [mail("m1", "Lunch on Friday?")]
        store(events, tmp_db)
        assert resolve_events(events, db_path=tmp_db) == {}

    def test_repo_url_mention_links_the_thread(self, tmp_db):
        seed = [gh("a", repo="u/proj", title="x")]
        store(seed, tmp_db)
        resolve_events(seed, db_path=tmp_db)

        events = [mail("m1", "review please", snippet="see github.com/u/proj for the diff", thread="t3")]
        store(events, tmp_db)
        assert resolve_events(events, db_path=tmp_db)["m1"] == "repo:u/proj"

    def test_configured_sender_domain_routes_email(self, tmp_db):
        cfg = Config({"workstreams": [
            {"name": "UCSD Admissions", "sender_domains": ["ucsd.edu"]},
        ]})
        events = [mail("m1", "Orientation details", sender="Admissions <hi@ucsd.edu>")]
        store(events, tmp_db)
        assignments = resolve_events(events, cfg=cfg, db_path=tmp_db)
        assert assignments["m1"] == "custom:ucsd-admissions"

    def test_short_aliases_are_ignored_to_avoid_false_links(self, tmp_db):
        cfg = Config({"workstreams": [{"name": "AI", "aliases": ["ai"]}]})
        events = [mail("m1", "air travel plans")]
        store(events, tmp_db)
        assert resolve_events(events, cfg=cfg, db_path=tmp_db) == {}


class TestConfigSeeding:
    def test_seed_creates_initiative_with_aliases(self, tmp_db):
        cfg = Config({"workstreams": [{"name": "OmanX", "aliases": ["oman scholars"]}]})
        seed_from_config(cfg, db_path=tmp_db)
        member_map = db.get_member_map(tmp_db)
        assert member_map[("alias", "omanx")] == "custom:omanx"
        assert member_map[("alias", "oman scholars")] == "custom:omanx"

    def test_seeding_twice_is_idempotent(self, tmp_db):
        cfg = Config({"workstreams": [{"name": "OmanX"}]})
        seed_from_config(cfg, db_path=tmp_db)
        seed_from_config(cfg, db_path=tmp_db)
        assert len(db.list_workstreams(tmp_db)) == 1


class TestWeekCounts:
    def test_counts_group_by_workstream_and_week(self, tmp_db):
        events = [gh("a"), gh("b")]
        store(events, tmp_db)
        resolve_events(events, db_path=tmp_db)
        counts = db.workstream_week_counts(["2026-W31"], tmp_db)
        assert counts == {"repo:MohammedAlkindi/Pulse": {"2026-W31": 2}}
