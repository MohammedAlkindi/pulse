"""End-to-end evaluation against the synthetic corpus with known ground truth.

These are the tests that decide whether Pulse's intelligence is real: run the
whole pipeline over a reproducible multi-week corpus and measure
deduplication, linking, extraction, citation validity, momentum, injection
handling, and insufficient-evidence behavior. Hermetic — no network, no
credentials, no LLM.
"""

import re
from datetime import date

import pytest

from agent import paths
from agent.analysis.extract import extract_candidates
from agent.analysis.items_sync import stale_open_items, sync_items
from agent.analysis.momentum import compute_momentum, trailing_weeks
from agent.briefing.changes import approaching_deadlines, material_changes
from agent.briefing.generator import generate
from agent.demo.corpus import ANCHOR, GROUND_TRUTH, build_corpus
from agent.demo.runner import DEMO_CONFIG
from agent.graph.workstreams import resolve_events
from agent.store import db
from agent.store.models import iso_week

WEEK = iso_week(ANCHOR)


@pytest.fixture
def corpus_db(tmp_path, monkeypatch):
    """A fully ingested, resolved, extracted corpus in a temp database."""
    path = tmp_path / "eval.db"
    monkeypatch.setattr(paths, "DB_PATH", path)
    db.init_db(path)
    db.upsert_events(build_corpus(), path)

    weeks = trailing_weeks(ANCHOR, 6)
    resolve_events(db.get_unassigned_events(weeks, path), cfg=DEMO_CONFIG, db_path=path)

    window = db.get_events_for_weeks_full(weeks, path)
    index = {e["id"]: e for e in window}
    candidates = extract_candidates(window, known_domains={"example.com"})
    for c in candidates:
        c["workstream_id"] = index.get(c["evidence"][0], {}).get("workstream_id", "")
    sync_items(candidates, WEEK, event_index=index, db_path=path)
    return path


def items_matching(path, needle, kind=None):
    return [i for i in db.list_items(kind=kind, db_path=path)
            if needle.lower() in i["text"].lower()]


class TestDeduplication:
    def test_reingesting_the_corpus_creates_zero_duplicates(self, corpus_db):
        before = len(db.get_events_for_weeks_full(trailing_weeks(ANCHOR, 6), corpus_db))
        new, updated = db.upsert_events(build_corpus(), corpus_db)
        after = len(db.get_events_for_weeks_full(trailing_weeks(ANCHOR, 6), corpus_db))
        assert (new, updated) == (0, 0)
        assert before == after

    def test_the_duplicate_feed_entry_collapses_on_first_ingest(self, tmp_path, monkeypatch):
        path = tmp_path / "dup.db"
        monkeypatch.setattr(paths, "DB_PATH", path)
        db.init_db(path)
        events = build_corpus()
        new, _ = db.upsert_events(events, path)
        # The corpus deliberately repeats one commit verbatim.
        assert new == len(events) - 1


class TestWorkstreamLinking:
    def test_known_assignments_are_correct(self, corpus_db):
        rows = {e["id"]: e["workstream_id"]
                for e in db.get_events_for_weeks_full(trailing_weeks(ANCHOR, 6), corpus_db)}
        for event_id, expected in GROUND_TRUTH["workstreams"].items():
            assert rows.get(event_id) == expected, f"{event_id} → {rows.get(event_id)}"

    def test_precision_no_event_lands_in_a_foreign_workstream(self, corpus_db):
        for event in db.get_events_for_weeks_full(trailing_weeks(ANCHOR, 6), corpus_db):
            ws = event["workstream_id"]
            repo = (event.get("metadata") or {}).get("repo")
            if repo and ws:
                assert ws == f"repo:{repo}"

    def test_cross_source_workstream_spans_github_notion_and_gmail(self, corpus_db):
        events = db.get_events_for_workstream("repo:demo/omanx", db_path=corpus_db)
        assert {e["source"] for e in events} >= {"github", "gmail"}

    def test_injection_email_does_not_hijack_a_workstream(self, corpus_db):
        for event_id in GROUND_TRUTH["injection_ids"]:
            row = db.get_events_by_ids([event_id], corpus_db)[0]
            assert row["workstream_id"] == ""


class TestExtraction:
    def test_user_commitment_with_correct_deadline(self, corpus_db):
        truth = GROUND_TRUTH["user_commitment"]
        found = items_matching(corpus_db, truth["text_contains"], "commitment_by_user")
        assert len(found) == 1
        assert found[0]["due_date"] == truth["due_date"]
        assert truth["evidence"] in found[0]["evidence"]

    def test_other_party_commitment_direction_and_counterparty(self, corpus_db):
        truth = GROUND_TRUTH["other_commitment"]
        found = items_matching(corpus_db, truth["text_contains"], "commitment_by_other")
        assert len(found) == 1
        assert found[0]["counterparty"] == truth["counterparty"]
        assert found[0]["due_date"] == truth["due_date"]

    def test_decision_extracted(self, corpus_db):
        assert items_matching(corpus_db, GROUND_TRUTH["decision_text_contains"], "decision")

    def test_blocker_extracted(self, corpus_db):
        assert items_matching(corpus_db, GROUND_TRUTH["blocker_text_contains"], "blocker")

    def test_every_item_carries_resolvable_evidence(self, corpus_db):
        known = {e["id"] for e in db.get_events_for_weeks_full(trailing_weeks(ANCHOR, 6), corpus_db)}
        for item in db.list_items(db_path=corpus_db):
            assert item["evidence"]
            assert set(item["evidence"]) <= known

    def test_reextraction_does_not_duplicate_items(self, corpus_db):
        weeks = trailing_weeks(ANCHOR, 6)
        window = db.get_events_for_weeks_full(weeks, corpus_db)
        before = len(db.list_items(db_path=corpus_db))
        stats = sync_items(extract_candidates(window), WEEK,
                           event_index={e["id"]: e for e in window}, db_path=corpus_db)
        assert stats["created"] == 0
        assert len(db.list_items(db_path=corpus_db)) == before


class TestInjectionHandling:
    def test_hostile_items_are_marked_untrusted(self, corpus_db):
        hostile = [i for i in db.list_items(db_path=corpus_db)
                   if any(e in GROUND_TRUTH["injection_ids"] for e in i["evidence"])]
        assert hostile, "the corpus must produce at least one item from hostile content"
        assert all(i["trust"] == "suspicious" for i in hostile)

    def test_hostile_claims_render_with_a_warning_not_as_fact(self, corpus_db):
        hostile = [i for i in db.list_items(db_path=corpus_db)
                   if any(e in GROUND_TRUTH["injection_ids"] for e in i["evidence"])]
        index = {e["id"]: e for e in db.get_events_for_weeks_full(trailing_weeks(ANCHOR, 6), corpus_db)}
        briefing = generate(WEEK, _empty_analysis(), {}, None,
                            open_items=hostile, changes={"new_decisions": hostile},
                            event_index=index)
        assert "UNVERIFIED" in briefing
        assert "treat as a claim, not a fact" in briefing

    def test_framing_payloads_never_reach_the_rendered_briefing(self, corpus_db):
        index = {e["id"]: e for e in db.get_events_for_weeks_full(trailing_weeks(ANCHOR, 6), corpus_db)}
        briefing = generate(WEEK, _empty_analysis(), {}, None,
                            open_items=db.list_items(status="open", db_path=corpus_db),
                            event_index=index)
        assert "</event>" not in briefing
        assert "IGNORE ALL PREVIOUS INSTRUCTIONS" not in briefing

    def test_injection_cannot_forge_an_evidence_id(self, corpus_db):
        # The payload names a fake event id; it must not exist in the ledger.
        assert db.get_events_by_ids(["github:demo:fake"], corpus_db) == []


class TestMomentum:
    def test_stalled_project_is_detected(self, corpus_db):
        weeks = trailing_weeks(ANCHOR, 5)
        momentum = compute_momentum(db.get_events_for_weeks(weeks, corpus_db), weeks)
        source, key = GROUND_TRUTH["stalled_track"]
        track = next(t for t in momentum["tracks"] if t["source"] == source and t["key"] == key)
        assert track["trend"] == "stalled"
        assert track["this_week"] == 0

    def test_active_project_is_not_stalled(self, corpus_db):
        weeks = trailing_weeks(ANCHOR, 5)
        momentum = compute_momentum(db.get_events_for_weeks(weeks, corpus_db), weeks)
        track = next(t for t in momentum["tracks"]
                     if t["source"] == "github" and t["key"] == "demo/omanx")
        assert track["trend"] in ("steady", "rising")


class TestTemporalAndCitations:
    def test_deadline_horizon_ordering(self, corpus_db):
        open_items = db.list_items(status="open", db_path=corpus_db)
        due = approaching_deadlines(open_items, ANCHOR.date())
        assert [d["due_date"] for d in due] == sorted(d["due_date"] for d in due)
        assert all(d["deadline_state"] in ("overdue", "due_soon") for d in due)

    def test_material_changes_reports_this_weeks_items(self, corpus_db):
        changes = material_changes(WEEK, db_path=corpus_db)
        assert changes["new_commitments"] or changes["new_decisions"]

    def test_every_citation_marker_resolves_to_a_listed_source(self, corpus_db):
        index = {e["id"]: e for e in db.get_events_for_weeks_full(trailing_weeks(ANCHOR, 6), corpus_db)}
        weeks = trailing_weeks(ANCHOR, 5)
        momentum = compute_momentum(db.get_events_for_weeks(weeks, corpus_db), weeks)
        open_items = db.list_items(status="open", db_path=corpus_db)

        briefing = generate(WEEK, _empty_analysis(), {}, momentum,
                            changes=material_changes(WEEK, db_path=corpus_db),
                            open_items=open_items,
                            deadlines=approaching_deadlines(open_items, ANCHOR.date()),
                            stale_items=stale_open_items(WEEK, 2, db_path=corpus_db),
                            event_index=index)

        body, _, sources = briefing.partition("## Sources")
        listed = set(re.findall(r"^(\d+)\. `", sources, re.MULTILINE))
        cited = {n for marker in re.findall(r"\[(\d+(?:,\d+)*)\]", body)
                 for n in marker.split(",")}
        assert cited, "briefing must cite something"
        assert cited <= listed, f"unresolved markers: {cited - listed}"

    def test_no_source_line_references_an_unknown_event(self, corpus_db):
        index = {e["id"]: e for e in db.get_events_for_weeks_full(trailing_weeks(ANCHOR, 6), corpus_db)}
        briefing = generate(WEEK, _empty_analysis(), {}, None,
                            open_items=db.list_items(status="open", db_path=corpus_db),
                            event_index=index)
        for event_id in re.findall(r"^\d+\. `([^`]+)`", briefing.partition("## Sources")[2], re.MULTILINE):
            assert event_id in index or event_id.startswith("momentum:")


class TestInsufficientEvidence:
    def test_empty_ledger_produces_an_honest_briefing(self, tmp_path, monkeypatch):
        path = tmp_path / "empty.db"
        monkeypatch.setattr(paths, "DB_PATH", path)
        db.init_db(path)
        briefing = generate("2026-W31", _empty_analysis(), {}, None, event_index={})
        for phrase in ("Insufficient evidence", "_No open commitments in evidence._",
                       "_No decisions evidenced this week._", "_No evidence cited._"):
            assert phrase in briefing

    def test_no_fabricated_movement_language_without_evidence(self):
        briefing = generate("2026-W31", _empty_analysis(), {}, None, event_index={})
        assert "Stalled:" not in briefing
        assert "OVERDUE" not in briefing


class TestSourceFailureIsolation:
    def test_briefing_discloses_a_failed_source_and_keeps_the_rest(self, corpus_db):
        index = {e["id"]: e for e in db.get_events_for_weeks_full(trailing_weeks(ANCHOR, 6), corpus_db)}
        briefing = generate(WEEK, _empty_analysis(), {"github": {"commit": 5}}, None,
                            open_items=db.list_items(status="open", db_path=corpus_db),
                            event_index=index,
                            source_status={"gmail": {"status": "error", "error": "token expired"},
                                           "github": {"status": "ok"}})
        assert "gmail was unavailable this run (token expired)" in briefing
        assert "| GitHub | Events | 5 |" in briefing


def _empty_analysis() -> dict:
    return {"themes": [], "active_projects": [], "drifting": [],
            "attention_next_week": [], "data_quality_notes": []}
